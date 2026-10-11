// Tooltips for icon buttons and short labels, in place of the browser's plain `title`:
//   <button use:tooltip={"Print bill"} aria-label="Print bill">…</button>
//   <span use:tooltip={{ text: "Paid in full", placement: "bottom" }}>…</span>
// Shows on hover (after a short pause) and on keyboard focus; Esc hides it. The bubble lives in <body>
// with position: fixed, so cards and tables that clip their content never cut it off, and it stays on screen.
// It isn't announced twice: buttons keep their aria-label, and the tooltip is aria-hidden.

type Options = string | { text: string; placement?: "top" | "bottom" };

let bubble: HTMLDivElement | null = null;
let owner: HTMLElement | null = null;

function el(): HTMLDivElement {
  if (!bubble) {
    bubble = document.createElement("div");
    bubble.className = "ui-tooltip";
    bubble.setAttribute("aria-hidden", "true");
    document.body.appendChild(bubble);
  }
  return bubble;
}

function open(node: HTMLElement, text: string, placement: "top" | "bottom") {
  if (!text) return;
  const b = el();
  owner = node;
  b.textContent = text;
  b.classList.remove("is-below");
  b.style.left = "0px";
  b.style.top = "0px";
  b.classList.add("is-open");
  const r = node.getBoundingClientRect(), w = b.offsetWidth, h = b.offsetHeight, gap = 8, margin = 8;
  let below = placement === "bottom" || r.top - h - gap < margin;
  if (below && r.bottom + h + gap > window.innerHeight - margin && r.top - h - gap >= margin) below = false;
  const left = Math.min(window.innerWidth - margin - w, Math.max(margin, r.left + r.width / 2 - w / 2));
  b.style.left = `${Math.round(left)}px`;
  b.style.top = `${Math.round(below ? r.bottom + gap : r.top - h - gap)}px`;
  b.classList.toggle("is-below", below);
}

function close(node?: HTMLElement) {
  if (bubble && (!node || owner === node)) { bubble.classList.remove("is-open"); owner = null; }
}

export function tooltip(node: HTMLElement, options: Options) {
  let opts = typeof options === "string" ? { text: options } : options;
  let timer: ReturnType<typeof setTimeout>;
  const show = (delay: number) => { clearTimeout(timer); timer = setTimeout(() => open(node, opts.text, opts.placement ?? "top"), delay); };
  const hide = () => { clearTimeout(timer); close(node); };
  const enter = (e: PointerEvent) => { if (e.pointerType !== "touch") show(350); };
  const focus = () => { if (node.matches(":focus-visible")) show(0); };
  const key = (e: KeyboardEvent) => { if (e.key === "Escape") hide(); };
  node.addEventListener("pointerenter", enter);
  node.addEventListener("pointerleave", hide);
  node.addEventListener("focus", focus);
  node.addEventListener("blur", hide);
  node.addEventListener("click", hide);
  node.addEventListener("keydown", key);
  window.addEventListener("scroll", hide, { passive: true, capture: true });
  return {
    update(next: Options) {
      opts = typeof next === "string" ? { text: next } : next;
      if (owner === node && bubble) bubble.textContent = opts.text;
    },
    destroy() {
      hide();
      node.removeEventListener("pointerenter", enter);
      node.removeEventListener("pointerleave", hide);
      node.removeEventListener("focus", focus);
      node.removeEventListener("blur", hide);
      node.removeEventListener("click", hide);
      node.removeEventListener("keydown", key);
      window.removeEventListener("scroll", hide, { capture: true });
    },
  };
}
