<script lang="ts">
  import type { Snippet } from "svelte";
  import { router } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";
  import { applyTheme, getTheme, type Theme } from "../lib/theme";

  let { children }: { children: Snippet } = $props();

  interface NavItem { href: string; label: string; show: () => boolean }

  const clientNav: NavItem[] = [
    { href: "/", label: "Dashboard", show: () => true },
    { href: "/staff", label: "Staff", show: () => session.can("staff.manage") },
    { href: "/settings", label: "Centre settings", show: () => session.can("settings.manage") },
    { href: "/activity", label: "Activity log", show: () => session.can("activity.view") },
  ];
  const platformNav: NavItem[] = [
    { href: "/", label: "Overview", show: () => true },
    { href: "/clients", label: "Clients", show: () => session.can("platform.clients.view") },
    { href: "/staff", label: "Platform staff", show: () => session.can("platform.staff.manage") },
    { href: "/activity", label: "Activity log", show: () => session.can("platform.activity.view") },
  ];

  const nav = $derived((session.isPlatform ? platformNav : clientNav).filter((i) => i.show()));
  const isCurrent = (href: string) => (href === "/" ? router.path === "/" : router.path.startsWith(href));

  let menuOpen = $state(false);
  let navOpen = $state(false);
  let theme = $state<Theme>(getTheme());

  function setTheme(t: Theme) {
    theme = t;
    applyTheme(t);
  }

  $effect(() => {
    router.path; // close the mobile menu after moving to another page
    navOpen = false;
    menuOpen = false;
  });
</script>

<a class="skip" href="#main">Skip to content</a>
<div class="shell" class:nav-open={navOpen}>
  <aside class="side" aria-label="Main menu">
    <div class="brand">
      <svg viewBox="0 0 32 32" width="28" height="28" aria-hidden="true"><rect width="32" height="32" rx="7" fill="var(--brand)"/>
        <path d="M9 17h4l2-6 3 11 2-5h3" fill="none" stroke="var(--on-brand)" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
      <div>
        <div class="product">Supreme DMS</div>
        <div class="workspace">{session.workspace?.name}</div>
      </div>
    </div>
    <nav>
      {#each nav as item (item.href)}
        <a href={item.href} aria-current={isCurrent(item.href) ? "page" : undefined}>{item.label}</a>
      {/each}
    </nav>
    <div class="soon muted">
      {#if !session.isPlatform}Billing, reports and imaging arrive in the next phases.{/if}
    </div>
  </aside>

  <div class="main-col">
    <header class="top">
      <button class="btn small menu-btn" aria-expanded={navOpen} aria-label="Menu" onclick={() => (navOpen = !navOpen)}>☰</button>
      <div class="grow"></div>
      <div class="user">
        <button class="btn small" aria-haspopup="menu" aria-expanded={menuOpen} onclick={() => (menuOpen = !menuOpen)}>
          <span class="avatar" aria-hidden="true">{session.me?.full_name.charAt(0).toUpperCase()}</span>
          <span class="name">{session.me?.full_name}</span>
        </button>
        {#if menuOpen}
          <div class="menu card" role="menu">
            <div class="who">
              <strong>{session.me?.full_name}</strong>
              <div class="muted">{session.me?.email}</div>
              <div class="muted">{session.me?.roles.join(", ")}</div>
            </div>
            <a role="menuitem" href="/change-password">Change password</a>
            <div class="theme" role="group" aria-label="Appearance">
              {#each [["system", "System"], ["light", "Light"], ["dark", "Dark"]] as [value, label]}
                <button class="btn small" aria-pressed={theme === value} onclick={() => setTheme(value as Theme)}>{label}</button>
              {/each}
            </div>
            <button role="menuitem" class="signout" onclick={() => session.logout()}>Sign out</button>
          </div>
        {/if}
      </div>
    </header>
    <main id="main" tabindex="-1">{@render children()}</main>
  </div>
</div>

<style>
  .skip { position: absolute; left: -999px; top: 8px; }
  .skip:focus { left: 8px; z-index: 200; background: var(--surface); padding: 8px 12px; border-radius: var(--radius); }
  .shell { display: grid; grid-template-columns: 232px 1fr; min-height: 100vh; }
  .side { background: var(--surface); border-right: 1px solid var(--border); padding: 16px 12px; display: flex; flex-direction: column; gap: 18px;
    position: sticky; top: 0; height: 100vh; }
  .brand { display: flex; gap: 10px; align-items: center; padding: 0 6px; }
  .product { font-weight: 700; }
  .workspace { font-size: 12px; color: var(--text-2); }
  nav { display: grid; gap: 2px; }
  nav a { padding: 8px 10px; border-radius: var(--radius); color: var(--text); text-decoration: none; font-weight: 500; }
  nav a:hover { background: var(--surface-2); }
  nav a[aria-current="page"] { background: var(--brand-tint); color: var(--brand-strong); font-weight: 600; }
  .soon { margin-top: auto; font-size: 12px; padding: 0 6px; }
  .main-col { min-width: 0; display: flex; flex-direction: column; }
  .top { display: flex; align-items: center; gap: 10px; padding: 10px 24px; border-bottom: 1px solid var(--border); background: var(--surface); }
  .menu-btn { display: none; }
  main { padding: 24px; max-width: 1200px; width: 100%; outline: none; }
  .user { position: relative; }
  .avatar { display: inline-grid; place-items: center; width: 22px; height: 22px; border-radius: 50%; background: var(--brand); color: var(--on-brand); font-size: 12px; }
  .menu { position: absolute; right: 0; top: calc(100% + 6px); width: 260px; padding: 8px; display: grid; gap: 4px; z-index: 50; }
  .menu .who { padding: 6px 8px 10px; border-bottom: 1px solid var(--border); margin-bottom: 4px; font-size: 13px; }
  .menu a, .menu .signout { padding: 8px; border-radius: var(--radius); color: var(--text); text-decoration: none; text-align: left;
    background: none; border: 0; font: inherit; cursor: pointer; }
  .menu a:hover, .menu .signout:hover { background: var(--surface-2); }
  .theme { display: flex; gap: 4px; padding: 4px 8px; }
  .theme [aria-pressed="true"] { background: var(--brand-tint); border-color: var(--brand); }
  @media (max-width: 860px) {
    .shell { grid-template-columns: 1fr; }
    .side { position: fixed; inset: 0 auto 0 0; width: 260px; z-index: 60; transform: translateX(-100%); transition: transform .15s; box-shadow: var(--shadow); }
    .nav-open .side { transform: none; }
    .menu-btn { display: inline-flex; }
    .name { display: none; }
    main { padding: 16px; }
  }
</style>
