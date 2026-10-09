// A thin progress bar along the top of the page while the app talks to the server, as in the Sandhata
// Registry. start()/done() are counted, so overlapping requests keep one bar going. Visual only: busy
// regions set aria-busy for screen readers.

let bar: HTMLDivElement | undefined;
let active = 0;
let progress = 0;
let trickle: ReturnType<typeof setInterval> | undefined;
let hide: ReturnType<typeof setTimeout> | undefined;
let show: ReturnType<typeof setTimeout> | undefined;

function ensure(): HTMLDivElement {
  if (bar) return bar;
  bar = document.createElement("div");
  bar.className = "top-loader";
  bar.setAttribute("aria-hidden", "true");
  bar.innerHTML = '<div class="top-loader-bar"><span class="top-loader-glow"></span></div>';
  document.body.appendChild(bar);
  return bar;
}

function set(p: number) {
  progress = Math.min(p, 0.994);
  (ensure().firstElementChild as HTMLElement).style.transform = `scaleX(${progress})`;
}

export function start(): void {
  active += 1;
  if (active > 1) return;
  clearTimeout(hide);
  // Quick answers (most of them) don't flash a bar at all.
  show = setTimeout(() => {
    const el = ensure();
    el.classList.remove("is-done");
    el.classList.add("is-loading");
    set(0.08);
    trickle = setInterval(() => set(progress + (1 - progress) * 0.08), 200);
  }, 150);
}

export function done(): void {
  active = Math.max(0, active - 1);
  if (active > 0) return;
  clearTimeout(show);
  clearInterval(trickle);
  if (!bar?.classList.contains("is-loading")) return;
  set(1);
  bar.classList.remove("is-loading");
  bar.classList.add("is-done");
  hide = setTimeout(() => set(0), 600);
}
