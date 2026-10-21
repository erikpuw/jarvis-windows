// The five control buttons (#controls) sit behind one round main button (#btn-controls) at the top-right corner. Opening it
// (class "open" on #controls, CSS does the rest: the five drop together into one column under it, in a vertical capsule)
// is a toggle; it also folds back by itself after IDLE_MS without a touch on any of the buttons, and on Escape.
const IDLE_MS = 4000;

export function mountControlsMenu(root: HTMLElement, toggle: HTMLButtonElement): void {
  let timer = 0;
  const set = (open: boolean) => {
    clearTimeout(timer);
    root.classList.toggle("open", open);
    toggle.setAttribute("aria-expanded", String(open));
    if (open) timer = window.setTimeout(() => set(false), IDLE_MS);
  };
  const isOpen = () => root.classList.contains("open");
  toggle.addEventListener("click", () => set(!isOpen()));
  // any touch on a button inside the open menu counts as activity: wait another IDLE_MS
  const touched = () => { if (isOpen()) set(true); };
  root.addEventListener("pointerdown", touched);
  root.addEventListener("click", touched); // keyboard activation and scripted clicks have no pointerdown
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && isOpen()) set(false); });
}
