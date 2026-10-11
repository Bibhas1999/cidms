<script lang="ts">
  import Icon from "./Icon.svelte";

  // The ⓘ toggletip from the Sandhata Registry: explains a field or a figure.
  //   <InfoTip text="What to enter…" about="Discount" />   (or give Field a `tip`)
  // Opens on hover, on keyboard focus of the button and on tap; the pointer can move onto the bubble;
  // Esc closes it. The bubble is placed with position: fixed, so cards, tables and dialogs that clip
  // their content never hide it; it flips below and shifts sideways to stay on screen.
  let { text, about = "this" }: { text: string; about?: string } = $props();

  const uid = $props.id();
  let open = $state(false);
  let below = $state(false);
  let pos = $state({ left: 0, top: 0, arrow: 0 });
  let wasOpen = false;
  let timer: ReturnType<typeof setTimeout>;
  let tip: HTMLSpanElement;
  let trigger: HTMLButtonElement;
  let bubble: HTMLSpanElement;

  const MARGIN = 8, GAP = 8;
  function place() {
    if (!trigger || !bubble) return;
    const t = trigger.getBoundingClientRect(), w = bubble.offsetWidth, h = bubble.offsetHeight;
    const center = t.left + t.width / 2;
    const left = Math.min(window.innerWidth - MARGIN - w, Math.max(MARGIN, center - w / 2));
    below = t.top - h - GAP < MARGIN;
    pos = { left, top: below ? t.bottom + GAP : t.top - h - GAP, arrow: Math.min(w - 12, Math.max(12, center - left)) };
  }
  function show() {
    clearTimeout(timer);
    if (!open) { document.dispatchEvent(new CustomEvent("infotip:open", { detail: uid })); open = true; }
    requestAnimationFrame(place);
  }
  const hide = () => { clearTimeout(timer); open = false; };
  const hideSoon = () => { clearTimeout(timer); timer = setTimeout(hide, 120); };

  $effect(() => {
    const others = (e: Event) => { if ((e as CustomEvent).detail !== uid) hide(); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape" && open) hide(); };
    const outside = (e: PointerEvent) => { if (open && !tip.contains(e.target as Node)) hide(); };
    const reflow = () => { if (open) place(); };
    document.addEventListener("infotip:open", others);
    document.addEventListener("keydown", key);
    document.addEventListener("pointerdown", outside);
    window.addEventListener("scroll", reflow, { passive: true, capture: true });
    window.addEventListener("resize", reflow);
    return () => {
      document.removeEventListener("infotip:open", others);
      document.removeEventListener("keydown", key);
      document.removeEventListener("pointerdown", outside);
      window.removeEventListener("scroll", reflow, { capture: true });
      window.removeEventListener("resize", reflow);
      clearTimeout(timer);
    };
  });
</script>

<span class="tip info-tip" class:is-open={open} class:is-below={below} bind:this={tip} role="presentation"
      onpointerenter={(e) => { if (e.pointerType !== "touch") show(); }}
      onpointerleave={(e) => { if (e.pointerType !== "touch" && document.activeElement !== trigger) hideSoon(); }}>
  <button type="button" class="tip-trigger" aria-label="More about {about}" aria-describedby="{uid}-tip" bind:this={trigger}
          onpointerdown={() => (wasOpen = open)} onfocus={show} onblur={hideSoon}
          onclick={(e) => { e.preventDefault(); e.stopPropagation(); if (wasOpen) hide(); else show(); wasOpen = false; }}>
    <Icon name="info" size="sm" />
  </button>
  <span class="tip-bubble info-bubble" role="tooltip" id="{uid}-tip" bind:this={bubble}
        style="left: {pos.left}px; top: {pos.top}px; --arrow-x: {pos.arrow}px">{text}</span>
</span>

<style>
  /* Sits on the text line it explains, whatever the container (labels, card titles, table headers). */
  .info-tip { display: inline-flex; align-items: center; vertical-align: middle; flex: none; margin: -4px 0; line-height: 1; }
  .info-tip .tip-trigger { width: 22px; height: 22px; }
  /* Fixed to the viewport (overrides the registry's absolute placement), above dialogs and sticky bars. */
  .info-tip .info-bubble { position: fixed; z-index: 1100; bottom: auto; right: auto; transform: none; }
  .info-tip .info-bubble::after { left: var(--arrow-x); }
  .info-tip.is-open .info-bubble::before { left: 0; right: 0; }
</style>
