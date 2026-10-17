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

/** The device that opens the session, sent as ?device= and kept per session on the server (Settings → Bộ nhớ shows
 *  "iPhone/iPad · iOS" instead of a bare web-xxxxxxxx). An iPad asks for the desktop site (Mac UA) but has touch. */
export function getDeviceType(): 'ios' | 'android' | 'mobile' | 'desktop' {
  const ua = typeof navigator !== 'undefined' ? (navigator.userAgent || '') : '';
  const isTouch = typeof navigator !== 'undefined' && (navigator.maxTouchPoints > 0);
  if (/iPhone|iPad|iPod/i.test(ua) || (/Macintosh/i.test(ua) && isTouch)) return 'ios';
  if (/Android/i.test(ua)) return 'android';
  const isMobileUA = /webOS|BlackBerry|IEMobile|Opera Mini/i.test(ua);
  const isSmallScreen = typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(max-width: 768px)').matches;
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
  // One chat session per page load, sent on every (re)connect: iOS drops the socket when the app goes to the
  // background but keeps the page and its bubbles, so a reconnect must stay in the same session on the server.
  const sessionId = "web-" + Array.from(crypto.getRandomValues(new Uint8Array(4)), (b) => b.toString(16).padStart(2, "0")).join("");

  function buildUrl(baseUrl: string): string {
    const sep = baseUrl.includes('?') ? '&' : '?';
    const device = baseUrl.includes('device=') ? '' : `device=${deviceType}&`;
    return `${baseUrl}${sep}${device}session=${sessionId}`;
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
