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
  /** The session id last confirmed by the server, null before the first `session` packet. */
  getSessionId(): string | null;
  /** Asks for this session id (null = a new one), closes the current socket and reconnects at once. */
  switchSession(id: string | null): void;
  /** Fired on each `session` packet; resumed is true when the server kept the id this socket asked for. */
  onSession(handler: (id: string, resumed: boolean) => void): void;
  /** Fired when the server closes with 1008 (bad token). The socket does not reconnect after that. */
  onAuthRejected(handler: () => void): void;
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
  let sessionHandlers: ((id: string, resumed: boolean) => void)[] = [];
  let authRejectedHandlers: (() => void)[] = [];
  let reconnectDelay = 1000;
  let closed = false;
  let authRejected = false;
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
  // Session id kept in memory only: the server assigns it (`session` packet) and a reload starts a new one.
  // requestedSessionId goes into the next connect URL; sessionId is what the server last confirmed.
  let requestedSessionId: string | null = null;
  let sessionId: string | null = null;

  function buildUrl(baseUrl: string): string {
    const params: string[] = [];
    if (!baseUrl.includes('device=')) params.push(`device=${deviceType}`);
    if (requestedSessionId) params.push(`session=${requestedSessionId}`);
    try {
      const token = localStorage.getItem("jarvis_token") || localStorage.getItem("jarvis_memory_token") || '';
      if (token) params.push(`token=${encodeURIComponent(token)}`);
    } catch {}
    if (params.length === 0) return baseUrl;
    return `${baseUrl}${baseUrl.includes('?') ? '&' : '?'}${params.join('&')}`;
  }

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
    if (closed || authRejected) return;
    clearReconnectTimer();
    console.log(`[ws] reconnecting in ${reconnectDelay}ms`);
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 30000);
  }

  function connect() {
    if (closed || authRejected) return;
    // Single-flight. A pending reconnect timer plus a manual reconnect used to
    // open two live sockets that shared one handler list, so every message was
    // handled twice — duplicated audio and duplicated chat bubbles.
    if (connecting) return;
    if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) return;
    clearReconnectTimer();
    connecting = true;

    // The session this socket asked for; the server's `session` packet tells whether it was kept.
    const asked = requestedSessionId;
    const socket = new WebSocket(buildUrl(url));
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
      if (ws !== socket) return;  // a packet still in flight on a detached socket must not touch the new session
      lastMessageAt = Date.now();
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "pong") return;  // transport-level, not for handlers
        if (msg.type === "session" && typeof msg.id === "string") {
          sessionId = msg.id;
          requestedSessionId = msg.id;
          for (const h of sessionHandlers) h(msg.id, msg.id === asked);
        }
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

      // 1008 = the server refused the token. Retrying would only repeat the refusal.
      if (event.code === 1008) {
        authRejected = true;
        console.warn("[ws] refused by server (1008) — not reconnecting");
        for (const h of authRejectedHandlers) h();
        return;
      }
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
    onSession(handler) {
      sessionHandlers.push(handler);
    },
    onAuthRejected(handler) {
      authRejectedHandlers.push(handler);
    },
    getSessionId() {
      return sessionId;
    },
    switchSession(id) {
      requestedSessionId = id;
      if (closed) return;
      // Detach the old socket first: its late onclose sees ws !== socket and does nothing.
      const old = ws;
      ws = null;
      connecting = false;
      connected = false;
      stopHeartbeat();
      clearReconnectTimer();
      reconnectDelay = 1000;
      old?.close();
      connect();
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
