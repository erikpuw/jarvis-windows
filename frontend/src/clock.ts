// HTC Sense–style flip clock without the card: one slot per digit (H H  M M),
// split across the middle.
// On change the old top half folds down over the split, then the new bottom
// half falls into place. Sits just above the orb (--z-clock, no pointer events).
import "@fontsource/oswald/latin-300.css"; // bundled: desktop app works offline

const HALF_MS = 300;

function card(): HTMLElement {
  const c = document.createElement("div");
  c.className = "fc";
  c.innerHTML = `<div class="fc-top"><span></span></div><div class="fc-bottom"><span></span></div>`;
  return c;
}

function half(cls: string, text: string): HTMLElement {
  const h = document.createElement("div");
  h.className = cls;
  h.innerHTML = `<span>${text}</span>`;
  return h;
}

function set(c: HTMLElement, value: string, animate: boolean) {
  const old = c.dataset.value;
  if (old === value) return;
  c.dataset.value = value;
  const top = c.querySelector(".fc-top span")!;
  const bottom = c.querySelector(".fc-bottom span")!;
  if (!animate || old === undefined || matchMedia("(prefers-reduced-motion: reduce)").matches) {
    top.textContent = bottom.textContent = value;
    return;
  }
  c.querySelectorAll(".fc-flap-top, .fc-flap-bottom").forEach((f) => f.remove());
  c.classList.remove("flipping");
  void c.offsetWidth; // restart the cross-fade animations
  c.classList.add("flipping");
  top.textContent = value; // fades in as the old top half folds away
  c.append(half("fc-flap-top", old), half("fc-flap-bottom", value));
  window.setTimeout(() => {
    bottom.textContent = value;
    c.classList.remove("flipping");
    c.querySelectorAll(".fc-flap-top, .fc-flap-bottom").forEach((f) => f.remove());
  }, HALF_MS * 2);
}

export function mountClock(parent: HTMLElement = document.body) {
  const root = document.createElement("div");
  root.id = "jarvis-clock";
  root.setAttribute("aria-hidden", "true");
  const digits = [card(), card(), card(), card()];
  const colon = document.createElement("div");
  colon.className = "fc-colon";
  colon.innerHTML = "<i></i><i></i>"; // two dots, each pinging a radar ring
  root.append(digits[0], digits[1], colon, digits[2], digits[3]);
  parent.appendChild(root);

  const tick = (animate: boolean) => {
    const d = new Date();
    const hhmm = [d.getHours(), d.getMinutes()].map((n) => String(n).padStart(2, "0")).join("");
    digits.forEach((c, i) => set(c, hhmm[i], animate));
  };
  tick(false);
  window.setInterval(() => tick(true), 1000);
}
