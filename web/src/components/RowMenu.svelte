<script lang="ts" module>
  // The ⋮ button at the end of every list row, opening that row's actions (DataTable adds it for you via
  // `actions`). Items are links or buttons:
  //   { label: "Print", icon: "printer", href: "/bills/1/print", newTab: true }
  //   { label: "Suspend", icon: "lock", onclick: () => …, tone: "danger", hint: "Signs everyone out" }
  //   { label: "Collect due", icon: "wallet", disabled: true, hint: "Nothing is due" }
  // `hint` shows as a tooltip on the item (and is read after the label). The menu is placed on the page
  // (position: fixed) so a table's scroll box never clips it, and it is kept inside the screen.
  export interface RowAction {
    label: string;
    icon: string;
    href?: string;
    newTab?: boolean;
    onclick?: () => void;
    tone?: "danger";
    hint?: string;
    disabled?: boolean;
  }
</script>

<script lang="ts">
  import { tooltip } from "../lib/tooltip";
  import Icon from "./Icon.svelte";

  let { actions, label = "Actions" }: { actions: RowAction[]; label?: string } = $props();

  let open = $state(false);
  let button = $state<HTMLButtonElement>();
  let menu = $state<HTMLElement>();
  let pos = $state({ top: 0, left: 0 });
  const uid = $props.id();

  function place() {
    const r = button!.getBoundingClientRect();
    const coarse = matchMedia("(pointer: coarse)").matches;
    const width = 220, height = actions.length * (coarse ? 44 : 38) + 12, m = 8;
    const below = r.bottom + 4 + height < window.innerHeight - m;
    const top = below ? r.bottom + 4 : Math.max(m, r.top - height - 4);
    const left = Math.min(window.innerWidth - width - m, Math.max(m, r.right - width));
    pos = { top, left };
  }

  function toggle(e: MouseEvent) {
    e.stopPropagation();
    if (open) { open = false; return; }
    place();
    open = true;
    queueMicrotask(() => (menu?.querySelector("a:not([aria-disabled]),button:not(:disabled)") as HTMLElement | null)?.focus());
  }

  $effect(() => {
    if (!open) return;
    const close = (e: Event) => { if (!menu?.contains(e.target as Node) && !button?.contains(e.target as Node)) open = false; };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") { open = false; button?.focus(); }
      if (e.key === "Tab") open = false;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const items = [...(menu?.querySelectorAll<HTMLElement>("a,button:not(:disabled)") ?? [])];
        const i = items.indexOf(document.activeElement as HTMLElement);
        items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length]?.focus();
      }
    };
    const away = () => (open = false);
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", key);
    window.addEventListener("scroll", away, { capture: true, passive: true });
    window.addEventListener("resize", away);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", key);
      window.removeEventListener("scroll", away, { capture: true });
      window.removeEventListener("resize", away);
    };
  });
</script>

<button bind:this={button} type="button" class="btn btn-ghost btn-icon btn-sm kebab" aria-label={label} use:tooltip={label}
        aria-haspopup="menu" aria-expanded={open} aria-controls={open ? `${uid}-menu` : undefined}
        onclick={toggle}><Icon name="moreVertical" size="sm" /></button>

{#if open}
  <div class="row-menu" role="menu" id="{uid}-menu" aria-label={label} bind:this={menu} style="top: {pos.top}px; left: {pos.left}px">
    {#each actions as a (a.label)}
      {#if a.href && !a.disabled}
        <a role="menuitem" class="row-menu-item" class:is-danger={a.tone === "danger"} href={a.href} use:tooltip={a.hint ?? ""}
           target={a.newTab ? "_blank" : undefined} rel={a.newTab ? "noopener" : undefined} onclick={(e) => { e.stopPropagation(); open = false; }}>
          <Icon name={a.icon} size="sm" /><span>{a.label}</span>{#if a.hint}<span class="sr-only">. {a.hint}</span>{/if}</a>
      {:else}
        <button role="menuitem" type="button" class="row-menu-item" class:is-danger={a.tone === "danger"} disabled={a.disabled}
                use:tooltip={a.hint ?? ""}
                onclick={(e) => { e.stopPropagation(); open = false; a.onclick?.(); }}><Icon name={a.icon} size="sm" /><span>{a.label}</span>{#if a.hint}<span class="sr-only">. {a.hint}</span>{/if}</button>
      {/if}
    {/each}
  </div>
{/if}

<style>
  .row-menu { position: fixed; z-index: 200; width: 220px; max-width: calc(100vw - 16px); padding: 5px; background: var(--popover); border: 1px solid var(--border);
    border-radius: 10px; box-shadow: var(--shadow-lg); }
  .row-menu-item { position: relative; display: flex; align-items: center; gap: 10px; width: 100%; height: 36px; padding: 0 10px; border: 0; border-radius: 7px;
    background: none; color: var(--foreground); font: 500 13.5px var(--font-sans); text-decoration: none !important; cursor: pointer; text-align: left; }
  .row-menu-item:hover:not(:disabled), .row-menu-item:focus-visible { background: var(--muted); }
  .row-menu-item:disabled { opacity: .5; cursor: not-allowed; }
  .row-menu-item :global(.icon) { color: var(--muted-foreground); flex: none; }
  .row-menu-item.is-danger { color: var(--destructive); }
  .row-menu-item.is-danger :global(.icon) { color: var(--destructive); }
  @media (pointer: coarse) {
    .row-menu-item { height: 42px; font-size: 14.5px; }
    .kebab { width: 40px !important; height: 40px !important; }
  }
</style>
