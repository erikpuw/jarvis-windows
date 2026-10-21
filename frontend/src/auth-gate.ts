/**
 * JARVIS Auth Gateway — Fullscreen Entry Gate
 *
 * Implements /ui-ux-pro-max guidelines:
 * - Fullscreen protective layer covering main.ts until authentication succeeds.
 * - Persistent session support via localStorage.
 * - Smooth glassmorphism UI with accessible labels, focus rings, and feedback.
 */

import { setMemoryToken, getMemoryToken } from "./settings/api";
import "./auth-gate.css";

export interface AuthUser {
  id: string;
  username: string;
  display_name?: string;
  role: "admin" | "member";
  tts_voice_id?: string;
  user_pronoun?: string;
  ai_pronoun?: string;
}

let currentUser: AuthUser | null = null;

export function getCurrentUser(): AuthUser | null {
  if (currentUser) return currentUser;
  try {
    const raw = localStorage.getItem("jarvis_user");
    if (raw) {
      currentUser = JSON.parse(raw);
      return currentUser;
    }
  } catch {}
  return null;
}

export function getCurrentUserRole(): "admin" | "member" {
  const u = getCurrentUser();
  return u?.role === "admin" ? "admin" : "member";
}

/**
 * Checks if user is already authenticated. If yes, resolves immediately.
 * If not, renders the fullscreen glassmorphic gate covering the entire page until login succeeds.
 */
export async function ensureAuthenticated(): Promise<AuthUser> {
  const existingToken = getMemoryToken();
  if (existingToken) {
    try {
      const res = await fetch("/api/auth/me", {
        headers: {
          "Authorization": `Bearer ${existingToken}`,
          "X-Memory-Token": existingToken,
        },
      });
      if (res.ok) {
        const body = await res.json();
        if (body.success && body.user) {
          currentUser = body.user;
          localStorage.setItem("jarvis_user", JSON.stringify(currentUser));
          return currentUser as AuthUser;
        }
      }
    } catch (e) {
      console.warn("[auth-gate] Existing token check failed:", e);
    }
    // Token is invalid/expired
    setMemoryToken("");
    localStorage.removeItem("jarvis_user");
    localStorage.removeItem("jarvis_active_session_id");
  }

  // Not authenticated: render fullscreen cover
  return new Promise<AuthUser>((resolve) => {
    let mode: "member" | "admin" = "member";

    // Lock background scroll on mobile & desktop
    const prevBodyOverflow = document.body.style.overflow;
    const prevHtmlOverflow = document.documentElement.style.overflow;
    const prevBodyTouchAction = document.body.style.touchAction;
    const prevHtmlOverscroll = document.documentElement.style.overscrollBehavior;

    document.body.style.overflow = "hidden";
    document.documentElement.style.overflow = "hidden";
    document.body.style.touchAction = "none";
    document.documentElement.style.overscrollBehavior = "none";

    const unlockScroll = () => {
      document.body.style.overflow = prevBodyOverflow;
      document.documentElement.style.overflow = prevHtmlOverflow;
      document.body.style.touchAction = prevBodyTouchAction;
      document.documentElement.style.overscrollBehavior = prevHtmlOverscroll;
    };

    const overlay = document.createElement("div");
    overlay.id = "auth-gate-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-labelledby", "auth-title");

    overlay.innerHTML = `
      <div class="auth-card">
        <div class="auth-header">
          <h1 class="auth-title" id="auth-title">Đăng nhập JARVIS</h1>
          <p class="auth-subtitle">Chọn loại tài khoản và nhập thông tin để truy cập.</p>
        </div>

        <div class="auth-tabs" role="tablist">
          <button type="button" class="auth-tab-btn active" id="tab-member" role="tab" aria-selected="true">
            <span>Thành viên</span>
          </button>
          <button type="button" class="auth-tab-btn" id="tab-admin" role="tab" aria-selected="false">
            <span>Quản trị</span>
          </button>
        </div>

        <form id="auth-form" autocomplete="off">
          <div id="field-member" class="auth-field">
            <label for="auth-uname" class="auth-label">Tên hiển thị</label>
            <input
              id="auth-uname"
              class="auth-input"
              type="text"
              placeholder="Nhập tên của bạn..."
              required
              maxlength="40"
              autocomplete="name"
            />
          </div>

          <div id="field-admin" class="auth-field" style="display: none;">
            <label for="auth-pass" class="auth-label">Mật khẩu quản trị</label>
            <input
              id="auth-pass"
              class="auth-input"
              type="password"
              placeholder="Nhập mật khẩu quản trị..."
              maxlength="100"
              autocomplete="current-password"
            />
          </div>

          <div id="auth-error-box" class="auth-error hidden" role="alert"></div>

          <button type="submit" id="auth-submit-btn" class="auth-submit-btn">
            <span>Tiếp tục</span>
          </button>

          <div class="auth-footnote">
            <svg class="auth-footnote-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="16" x2="12" y2="12"></line>
              <line x1="12" y1="8" x2="12.01" y2="8"></line>
            </svg>
            <span>Dữ liệu và bộ nhớ hội thoại được cô lập riêng biệt.</span>
          </div>
        </form>
      </div>
    `;

    document.body.appendChild(overlay);

    const tabMember = overlay.querySelector<HTMLButtonElement>("#tab-member")!;
    const tabAdmin = overlay.querySelector<HTMLButtonElement>("#tab-admin")!;
    const fieldMember = overlay.querySelector<HTMLElement>("#field-member")!;
    const fieldAdmin = overlay.querySelector<HTMLElement>("#field-admin")!;
    const inputUname = overlay.querySelector<HTMLInputElement>("#auth-uname")!;
    const inputPass = overlay.querySelector<HTMLInputElement>("#auth-pass")!;
    const errorBox = overlay.querySelector<HTMLElement>("#auth-error-box")!;
    const submitBtn = overlay.querySelector<HTMLButtonElement>("#auth-submit-btn")!;
    const form = overlay.querySelector<HTMLFormElement>("#auth-form")!;

    inputUname.focus();

    // Prevent any scrolling / rubber-banding on mobile browsers
    overlay.addEventListener(
      "touchmove",
      (e) => {
        e.preventDefault();
      },
      { passive: false }
    );

    // Tab switching
    tabMember.addEventListener("click", () => {
      mode = "member";
      tabMember.classList.add("active");
      tabMember.setAttribute("aria-selected", "true");
      tabAdmin.classList.remove("active");
      tabAdmin.setAttribute("aria-selected", "false");
      fieldMember.style.display = "flex";
      fieldAdmin.style.display = "none";
      inputUname.required = true;
      inputPass.required = false;
      errorBox.classList.add("hidden");
      submitBtn.querySelector("span")!.textContent = "Tiếp tục";
      inputUname.focus();
    });

    tabAdmin.addEventListener("click", () => {
      mode = "admin";
      tabAdmin.classList.add("active");
      tabAdmin.setAttribute("aria-selected", "true");
      tabMember.classList.remove("active");
      tabMember.setAttribute("aria-selected", "false");
      fieldMember.style.display = "none";
      fieldAdmin.style.display = "flex";
      inputUname.required = false;
      inputPass.required = true;
      errorBox.classList.add("hidden");
      submitBtn.querySelector("span")!.textContent = "Tiếp tục";
      inputPass.focus();
    });

    // Form submit
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      errorBox.classList.add("hidden");
      submitBtn.disabled = true;
      const originalText = submitBtn.querySelector("span")!.textContent;
      submitBtn.querySelector("span")!.textContent = "Đang xác thực...";

      try {
        const payload = mode === "admin"
          ? { username: "admin", password: inputPass.value }
          : { username: inputUname.value.trim() };

        const res = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });

        const data = await res.json().catch(() => ({}));

        if (!res.ok || !data.success || !data.token) {
          throw new Error(data.error || "Đăng nhập không thành công");
        }

        // Login success: save tokens and ensure fresh chat session
        setMemoryToken(data.token);
        currentUser = data.user;
        localStorage.setItem("jarvis_user", JSON.stringify(currentUser));
        localStorage.removeItem("jarvis_active_session_id");

        // Smooth exit animation
        overlay.classList.add("fade-out");
        setTimeout(() => {
          unlockScroll();
          overlay.remove();
          resolve(currentUser!);
        }, 350);
      } catch (err) {
        errorBox.textContent = err instanceof Error ? err.message : String(err);
        errorBox.classList.remove("hidden");
        submitBtn.disabled = false;
        submitBtn.querySelector("span")!.textContent = originalText;
      }
    });
  });
}
