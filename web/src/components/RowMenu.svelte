<script lang="ts">
  import Icon from "./Icon.svelte";

  // The ⋮ button at the end of a table row, opening that row's actions. The menu is placed on the page
  // (position: fixed) so a table's scroll box never clips it. Items are links or buttons.
  export interface RowAction {
    label: string;
    icon: string;
    href?: string;
    newTab?: boolean;
    onclick?: () => void;
    tone?: "danger";
  }

  let { actions, label = "Actions" }: { actions: RowAction[]; label?: string } = $props();

  let open = $state(false);
  let button = $state<HTMLButtonElement>();
  let menu = $state<HTMLElement>();
  let pos = $state({ top: 0, left: 0 });

  function toggle(e: MouseEvent) {
    e.stopPropagation();
    if (open) { open = false; return; }
    const r = button!.getBoundingClientRect();
    const width = 200, height = actions.length * 38 + 10;
    const below = r.bottom + 4 + height < window.innerHeight;
    pos = { top: below ? r.bottom + 4 : r.top - height - 4, left: Math.max(8, r.right - width) };
    open = true;
    queueMicrotask(() => (menu?.querySelector("a,button") as HTMLElement | null)?.focus());
  }

  $effect(() => {
    if (!open) return;
    const close = (e: Event) => { if (!menu?.contains(e.target as Node) && e.target !== button) open = false; };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") { open = false; button?.focus(); }
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const items = [...(menu?.querySelectorAll<HTMLElement>("a,button") ?? [])];
        const i = items.indexOf(document.activeElement as HTMLElement);
        items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length]?.focus();
      }
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", key);
    window.addEventListener("scroll", () => (open = false), { once: true, capture: true });
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", key); };
  });
</script>

<button bind:this={button} type="button" class="btn btn-ghost btn-icon btn-sm kebab" aria-label={label} title={label}
        aria-haspopup="menu" aria-expanded={open} onclick={toggle}><Icon name="moreVertical" size="sm" /></button>

{#if open}
  <div class="row-menu" role="menu" bind:this={menu} style="top: {pos.top}px; left: {pos.left}px">
    {#each actions as a (a.label)}
      {#if a.href}
        <a role="menuitem" class="row-menu-item" class:is-danger={a.tone === "danger"} href={a.href}
           target={a.newTab ? "_blank" : undefined} rel={a.newTab ? "noopener" : undefined} onclick={(e) => { e.stopPropagation(); open = false; }}>
          <Icon name={a.icon} size="sm" />{a.label}</a>
      {:else}
        <button role="menuitem" type="button" class="row-menu-item" class:is-danger={a.tone === "danger"}
                onclick={(e) => { e.stopPropagation(); open = false; a.onclick?.(); }}><Icon name={a.icon} size="sm" />{a.label}</button>
      {/if}
    {/each}
  </div>
{/if}

<style>
  .row-menu { position: fixed; z-index: 200; width: 200px; padding: 5px; background: var(--popover); border: 1px solid var(--border);
    border-radius: 10px; box-shadow: var(--shadow-lg); }
  .row-menu-item { display: flex; align-items: center; gap: 10px; width: 100%; height: 36px; padding: 0 10px; border: 0; border-radius: 7px;
    background: none; color: var(--foreground); font: 500 13.5px var(--font-sans); text-decoration: none !important; cursor: pointer; text-align: left; }
  .row-menu-item:hover, .row-menu-item:focus-visible { background: var(--muted); }
  .row-menu-item :global(.icon) { color: var(--muted-foreground); }
  .row-menu-item.is-danger { color: var(--destructive); }
  .row-menu-item.is-danger :global(.icon) { color: var(--destructive); }
</style>
