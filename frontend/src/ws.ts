/**
 * WebSocket client for JARVIS server communication.
 */

export type MessageHandler = (msg: Record<string, unknown>) => void;

export interface JarvisSocket {
  /** Returns false when the socket was not open and the message was dropped. */
  send(data: Record<string, unknown>): boolean;
  onMessage(handler: MessageHandler): void;
  onReconnect(handler: () => void): void;
  close(): void;
  /** Tries to connect right now (resets the backoff) unless a socket is already open or connecting. */
  retryNow(): void;
  isConnected(): boolean;
}

export function getDeviceType(): 'mobile' | 'desktop' {
  const ua = typeof navigator !== 'undefined' ? (navigator.userAgent || '') : '';
  const isMobileUA = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(ua);
  const isSmallScreen = typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(max-width: 768px)').matches;
  const isTouch = typeof navigator !== 'undefined' && (navigator.maxTouchPoints > 0);
  return (isMobileUA || (isSmallScreen && isTouch)) ? 'mobile' : 'desktop';
}

export function createSocket(url: string): JarvisSocket {
  let ws: WebSocket | null = null;
  let handlers: MessageHandler[] = [];
  let reconnectHandlers: (() => void)[] = [];
  let reconnectDelay = 1000;
  let closed = false;
  let connected = false;
  let everConnected = false;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  let connecting = false;
  let lastMessageAt = 0;

  const HEARTBEAT_INTERVAL_MS = 20000;
  // A half-open socket reports OPEN forever; only silence gives it away.
  const STALE_AFTER_MS = 60000;

  const deviceType = getDeviceType();

  function buildUrl(baseUrl: string): string {
    if (baseUrl.includes('device=')) return baseUrl;
    const sep = baseUrl.includes('?') ? '&' : '?';
    return `${baseUrl}${sep}device=${deviceType}`;
  }

  const finalUrl = buildUrl(url);

  function clearReconnectTimer() {
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  }

  function stopHeartbeat() {
    if (heartbeatTimer !== null) {
      clearInterval(heartbeatTimer);
      heartbeatTimer = null;
    }
  }

  function startHeartbeat(socket: WebSocket) {
    stopHeartbeat();
    lastMessageAt = Date.now();
    heartbeatTimer = setInterval(() => {
      if (socket.readyState !== WebSocket.OPEN) return;
      if (Date.now() - lastMessageAt > STALE_AFTER_MS) {
        console.warn("[ws] no traffic for 60s — connection is dead, reconnecting");
        stopHeartbeat();
        socket.close();
        return;
      }
      try {
        socket.send(JSON.stringify({ type: "ping" }));
      } catch {
        /* onclose will handle it */
      }
    }, HEARTBEAT_INTERVAL_MS);
  }

  function scheduleReconnect() {
    if (closed) return;
    clearReconnectTimer();
    console.log(`[ws] reconnecting in ${reconnectDelay}ms`);
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 30000);
  }

  function connect() {
    if (closed) return;
    // Single-flight. A pending reconnect timer plus a manual reconnect used to
    // open two live sockets that shared one handler list, so every message was
    // handled twice — duplicated audio and duplicated chat bubbles.
    if (connecting) return;
    if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) return;
    clearReconnectTimer();
    connecting = true;

    const socket = new WebSocket(finalUrl);
    ws = socket;

    socket.onopen = () => {
      connecting = false;
      connected = true;
      reconnectDelay = 1000;
      startHeartbeat(socket);
      if (everConnected) {
        console.log("[ws] reconnected — server is back up");
        for (const h of reconnectHandlers) h();
      }
      everConnected = true;
      console.log(`[ws] connected (${deviceType})`);
      // Đồng bộ trạng thái tts_disabled từ localStorage khi kết nối/kết nối lại
      const isTtsDisabled = localStorage.getItem("jarvis_tts_disabled") === "true";
      if (isTtsDisabled) {
        ws?.send(JSON.stringify({ type: "toggle_tts", enabled: false }));
      }
    };

    socket.onmessage = (event) => {
      lastMessageAt = Date.now();
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "pong") return;  // transport-level, not for handlers
        for (const h of handlers) h(msg);
      } catch {
        console.warn("[ws] bad message", event.data);
      }
    };

    socket.onclose = (event) => {
      connecting = false;
      if (ws !== socket) return;  // a stale socket closing late
      connected = false;
      stopHeartbeat();

      if (!closed) scheduleReconnect();
    };

    socket.onerror = (err) => {
      console.error("[ws] error", err);
      // Close THIS socket. Reading the closure variable here killed whichever
      // socket was current, so a late error from an old socket tore down the
      // freshly connected one.
      socket.close();
    };
  }

  connect();

  return {
    send(data) {
      // Returns delivery status: silently dropping a command left the UI stuck
      // in "thinking..." forever, because the caller assumed it had been sent.
      if (ws?.readyState === WebSocket.OPEN) {
        try {
          ws.send(JSON.stringify(data));
          return true;
        } catch (e) {
          console.error("[ws] send failed", e);
          return false;
        }
      }
      console.warn("[ws] send dropped — socket not open:", data?.type);
      return false;
    },
    onMessage(handler) {
      handlers.push(handler);
    },
    onReconnect(handler) {
      reconnectHandlers.push(handler);
    },
    close() {
      closed = true;
      clearReconnectTimer();
      stopHeartbeat();
      ws?.close();
    },
    retryNow() {
      if (closed || connected || connecting) return;
      reconnectDelay = 1000;
      connect();
    },
    isConnected() {
      return connected;
    },
  };
}
