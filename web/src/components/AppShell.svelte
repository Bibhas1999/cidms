<script lang="ts">
  import { tooltip } from "../lib/tooltip";
  import type { Snippet } from "svelte";
  import { confirmDialog } from "../lib/confirm.svelte";
  import { install } from "../lib/install.svelte";
  import { notify } from "../lib/toast.svelte";
  import { CLIENT_NAV, PLATFORM_NAV } from "../lib/nav";
  import { router } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";
  import { applyTheme, getTheme, type Theme } from "../lib/theme";
  import Avatar from "./Avatar.svelte";
  import Credit from "./Credit.svelte";
  import NotificationBell from "./NotificationBell.svelte";
  import Icon from "./Icon.svelte";

  // The app frame, laid out like the Sandhata Registry: sidebar with grouped sections, a top bar with
  // breadcrumbs and the profile menu, and the page. `available` = paths that have a page.
  let { title, available, children }: { title: string; available: Set<string>; children: Snippet } = $props();

  const sections = $derived(
    (session.isPlatform ? PLATFORM_NAV : CLIENT_NAV)
      .map((s) => ({ ...s, items: s.items.filter((i) => available.has(i.href.split("?")[0]) && (!i.permission || session.can(i.permission))) }))
      .filter((s) => s.items.length),
  );
  // An item with a ?query (e.g. /worklist?tab=scanned) is current only with that query; the plain item for
  // the same page then isn't. Report screens (/test-reports/…) belong to "Test reports".
  const queryItems = $derived(sections.flatMap((sec) => sec.items).filter((i) => i.href.includes("?")));
  const queryMatch = (href: string) => {
    const [base, q] = href.split("?");
    const want = new URLSearchParams(q), have = router.query;
    return router.path === base && [...want].every(([k, v]) => have.get(k) === v);
  };
  const isCurrent = (href: string) => {
    if (href.includes("?")) return queryMatch(href) || (href.startsWith("/worklist") && router.path.startsWith("/test-reports/"));
    if (queryItems.some((i) => queryMatch(i.href) || (i.href.startsWith(href) && router.path.startsWith("/test-reports/")))) return false;
    return href === "/" ? router.path === "/" : router.path === href || (router.path.startsWith(href + "/") && !available.has(router.path));
  };

  const ws = $derived(session.workspace);
  const local = location.hostname.endsWith(".localhost");

  let navOpen = $state(false);
  let menuOpen = $state(false);
  let theme = $state<Theme>(getTheme());
  let menuButton = $state<HTMLButtonElement>();
  let menu = $state<HTMLElement>();
  let navToggle = $state<HTMLButtonElement>();
  let sidebarEl = $state<HTMLElement>();

  // The desktop sidebar: full (icon + label), half (icon only, the label as a hover tooltip) or hidden
  // (the page takes the room). Remembered per browser; only matters above the 900px breakpoint where the
  // sidebar is static rather than the phone/tablet drawer `navOpen` governs.
  type SidebarMode = "full" | "half" | "hidden";
  function readSidebarMode(): SidebarMode {
    try {
      const v = localStorage.getItem("sidebar-mode");
      if (v === "full" || v === "half" || v === "hidden") return v;
    } catch { /* private browsing, blocked storage: default to full */ }
    return "full";
  }
  let sidebarMode = $state<SidebarMode>(readSidebarMode());
  const NEXT_MODE: Record<SidebarMode, SidebarMode> = { full: "half", half: "hidden", hidden: "full" };
  const NEXT_MODE_LABEL: Record<SidebarMode, string> = { full: "Collapse to icons only", half: "Hide the sidebar", hidden: "Show the full sidebar" };
  $effect(() => {
    try { localStorage.setItem("sidebar-mode", sidebarMode); } catch { /* ignore */ }
  });
  function cycleSidebar() { sidebarMode = NEXT_MODE[sidebarMode]; }

  $effect(() => {
    router.path; // close menus after moving to another page
    navOpen = false;
    menuOpen = false;
  });

  // Close the profile menu on a click outside it or Esc, and give focus back to its button.
  $effect(() => {
    if (!menuOpen) return;
    const onClick = (e: MouseEvent) => {
      if (!menu?.contains(e.target as Node) && !menuButton?.contains(e.target as Node)) menuOpen = false;
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { menuOpen = false; menuButton?.focus(); }
    };
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("click", onClick); document.removeEventListener("keydown", onKey); };
  });

  // Phones and tablets: the sidebar is a drawer. Opening it moves focus inside and traps Tab there; Esc closes
  // it and gives focus back to the toggle button; the page behind doesn't scroll while it's open.
  $effect(() => {
    if (!navOpen) return;
    const focusables = () => [...(sidebarEl?.querySelectorAll<HTMLElement>("a[href], button:not([disabled])") ?? [])];
    focusables()[0]?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { navOpen = false; navToggle?.focus(); return; }
      if (e.key !== "Tab") return;
      const items = focusables();
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    document.documentElement.classList.add("nav-locked");
    return () => { document.removeEventListener("keydown", onKey); document.documentElement.classList.remove("nav-locked"); };
  });

  /** Hand the computer to a colleague: sign out at once and show the accounts used here. */
  async function switchAccount() {
    menuOpen = false;
    await session.logout({ switching: true });
  }

  // Install Supreme DMS as an app (its own window and icon). iPhones: Share → Add to Home Screen.
  async function installApp() {
    menuOpen = false;
    if (install.prompt) {
      if (await install.run()) notify("Supreme DMS is installed. Open it from your desktop, Start menu or home screen.", { kind: "success" });
    } else if (install.ios) {
      notify("Tap the Share button in Safari, then “Add to Home Screen”.", { kind: "info", title: "Install on iPhone or iPad", duration: 15000 });
    }
  }

  async function signOut() {
    menuOpen = false;
    if (await confirmDialog({ title: "Sign out of CIDMS?", message: "You'll need your email and password to come back.",
                              confirmLabel: "Sign out", tone: "danger" })) await session.logout();
  }
</script>

<a class="skip-link" href="#main">Skip to main content</a>
<div class="app" class:nav-open={navOpen} class:sidebar-half={sidebarMode === "half"} class:sidebar-hidden={sidebarMode === "hidden"}>
  <aside class="sidebar" aria-label="Main navigation" bind:this={sidebarEl}>
    <div class="sidebar-brand">
      {#if sidebarMode === "half"}
        <a href="/" class="link-reset row brand-link brand-link-half" aria-label="{session.isPlatform ? 'CIDMS' : ws?.name}: dashboard">
          {#if ws?.logo_url}<img class="centre-logo" src={ws.logo_url} alt="" width="34" height="34" />{:else}<span class="centre-mark"><Icon name="activity" /></span>{/if}
        </a>
      {:else if !session.isPlatform && ws?.wordmark_url}
        <a href="/" class="link-reset brand-link wordmark-link" aria-label="{ws.name}: dashboard">
          <img class="centre-wordmark" src={ws.wordmark_url} alt={ws.name} />
        </a>
      {:else}
      <a href="/" class="link-reset row brand-link" style="gap: 10px">
        {#if ws?.logo_url}
          <img class="centre-logo" src={ws.logo_url} alt="" width="34" height="34" />
        {:else}
          <span class="centre-mark"><Icon name="activity" /></span>
        {/if}
        <span class="grow">
          <span class="centre-name truncate" style="display:block">{session.isPlatform ? "CIDMS" : ws?.name}</span>
          <span class="centre-sub">{session.isPlatform ? "Platform" : "DMS"}</span>
        </span>
      </a>
      {/if}
    </div>
    <nav class="sidebar-nav" aria-label="Sections">
      {#each sections as section (section.heading)}
        <div class="nav-heading" role="presentation">{section.heading}</div>
        {#each section.items as item (item.href)}
          <a class="nav-link" class:is-active={isCurrent(item.href)} href={item.href} aria-current={isCurrent(item.href) ? "page" : undefined}
             use:tooltip={{ text: sidebarMode === "half" ? item.label : "", placement: "top" }}>
            <Icon name={item.icon} /><span>{item.label}</span>
          </a>
        {/each}
      {/each}
    </nav>
    <div class="sidebar-footer">
      {#if sidebarMode !== "half"}<Credit /><a class="terms-link" href="/terms">Terms</a>{/if}
    </div>
  </aside>
  {#if navOpen}<button class="nav-backdrop" type="button" aria-label="Close menu" onclick={() => (navOpen = false)}></button>{/if}

  <div class="main">
    <header class="topbar">
      <button class="btn btn-ghost btn-icon menu-toggle" type="button" bind:this={navToggle} aria-label={navOpen ? "Close menu" : "Open menu"} use:tooltip={navOpen ? "Close menu" : "Open menu"}
              aria-expanded={navOpen} onclick={() => (navOpen = !navOpen)}><Icon name="menu" /></button>
      <button class="btn btn-ghost btn-icon sidebar-toggle" type="button" use:tooltip={NEXT_MODE_LABEL[sidebarMode]} aria-label={NEXT_MODE_LABEL[sidebarMode]}
              onclick={cycleSidebar}><Icon name="panelLeft" /></button>
      {#if sidebarMode === "hidden"}
        <a href="/" class="link-reset row topbar-brand" aria-label="{session.isPlatform ? 'CIDMS' : ws?.name}: dashboard">
          {#if ws?.logo_url}
            <img class="topbar-logo" src={ws.logo_url} alt="" width="28" height="28" />
          {:else}
            <span class="centre-mark topbar-mark"><Icon name="activity" /></span>
          {/if}
        </a>
      {/if}
      <nav class="breadcrumbs grow" aria-label="Breadcrumb">
        <a href="/" class="text-muted">{session.isPlatform ? "Platform" : ws?.name}</a>
        <Icon name="chevronRight" size="sm" />
        <strong aria-current="page">{title}</strong>
      </nav>
      {#if local}<span class="badge badge-info badge-plain hide-sm" use:tooltip={"Running on this computer"}>Local</span>{/if}
      <div class="topbar-actions">
        <NotificationBell />
        <div class="popover-anchor">
          <button class="profile-button" type="button" bind:this={menuButton} aria-haspopup="true" aria-expanded={menuOpen}
                  onclick={() => (menuOpen = !menuOpen)}>
            <Avatar name={session.me?.full_name ?? ""} url={session.me?.avatar_url} size="sm" />
            <span class="profile-name hide-sm">{session.me?.full_name.split(" ")[0]}</span>
            <Icon name="chevronDown" size="sm" />
            <span class="sr-only">Account menu for {session.me?.full_name}</span>
          </button>
          {#if menuOpen}
            <section class="popover profile-menu" aria-label="Account" bind:this={menu}>
              <div class="profile-head">
                <Avatar name={session.me?.full_name ?? ""} url={session.me?.avatar_url} />
                <div class="grow">
                  <div class="font-semibold truncate" use:tooltip={session.me?.full_name ?? ""}>{session.me?.full_name}</div>
                  <div class="text-xs text-muted truncate" use:tooltip={session.me?.email ?? ""}>{session.me?.email}</div>
                  {#each session.me?.roles ?? [] as role}<span class="badge badge-info badge-plain mt-2">{role}</span>{/each}
                </div>
              </div>
              <fieldset class="theme-switch">
                <legend class="sr-only">Theme</legend>
                <span class="theme-label" aria-hidden="true">Theme</span>
                <div class="theme-icons">
                  {#each [["light", "Light", "sun"], ["dark", "Dark", "moon"], ["system", "Match system", "monitor"]] as [value, label, ic] (value)}
                    <label class="theme-option" use:tooltip={label}>
                      <input type="radio" name="theme" class="sr-only" {value} checked={theme === value}
                             onchange={() => { theme = value as Theme; applyTheme(theme); }} />
                      <span><Icon name={ic} size="sm" /><span class="sr-only">{label}</span></span>
                    </label>
                  {/each}
                </div>
              </fieldset>
              <div class="profile-signout">
                <a class="btn btn-ghost btn-block menu-item" href="/settings"><Icon name="settings" /> Settings</a>
                {#if install.available}
                  <button class="btn btn-ghost btn-block menu-item" type="button" onclick={installApp}><Icon name="download" /> Install app</button>
                {/if}
                <button class="btn btn-ghost btn-block menu-item" type="button" onclick={switchAccount}><Icon name="users" /> Switch account</button>
                <button class="btn btn-ghost btn-block menu-item" type="button" onclick={signOut}><Icon name="logout" /> Sign out</button>
              </div>
            </section>
          {/if}
        </div>
      </div>
    </header>
    <main id="main" class="page" tabindex="-1">{@render children()}</main>
  </div>
</div>

<style>
  /* Room above and below the wordmark, so it doesn't sit on the top edge of the window. */
  .wordmark-link { display: flex; align-items: center; width: 100%; height: 100%; padding: 10px 0; box-sizing: border-box; }
  .sidebar-brand .centre-wordmark { display: block; width: 100%; max-width: 196px; height: auto; max-height: 40px; object-fit: contain; object-position: left center; }
  .sidebar-footer { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .terms-link { font-size: 12px; color: var(--faint-foreground, var(--muted-foreground)); text-decoration: none; }
  .terms-link:hover { color: var(--foreground); text-decoration: underline; }

  /* The desktop sidebar's three widths: full (icon + label), half (icon only) and hidden (the page takes the
     room), cycled from one toggle in the topbar (so it's reachable whichever width the sidebar is at right
     now). Only above the 900px breakpoint — on phones/tablets the sidebar stays the drawer `navOpen` opens. */
  .app { transition: grid-template-columns .15s ease; }
  .app.sidebar-half { grid-template-columns: 64px 1fr; }
  .app.sidebar-hidden { grid-template-columns: 1fr; }
  .app.sidebar-hidden .sidebar { display: none; }

  .sidebar-half .sidebar-brand { padding-left: 0; padding-right: 0; justify-content: center; }
  .brand-link-half { justify-content: center; padding: 8px 0; }
  .sidebar-half .nav-heading { display: none; }
  .sidebar-half .nav-link { justify-content: center; padding: 0; gap: 0; }
  /* Visually hidden, not display:none: the link's accessible name still comes from this text, same as a
     sighted mouse user getting it from the hover tooltip instead of reading it on the rail. */
  .sidebar-half .nav-link span {
    position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden;
    clip: rect(0 0 0 0); white-space: nowrap; border: 0;
  }

  /* Hidden: the sidebar's own logo is gone with it, so the topbar shows a small one in its place. */
  .topbar-brand { flex: none; margin-right: 4px; }
  .topbar-logo { width: 28px; height: 28px; border-radius: 7px; object-fit: contain; flex: none; }
  .topbar-mark { width: 28px; height: 28px; font-size: 13px; }

  @media (max-width: 900px) {
    /* Phones/tablets keep the drawer: full/half/hidden is a desktop-only preference. */
    .app.sidebar-half, .app.sidebar-hidden { grid-template-columns: var(--sidebar-width) 1fr; }
    .app.sidebar-hidden .sidebar { display: flex; }
    .sidebar-toggle, .topbar-brand { display: none; }
  }
  @media (prefers-reduced-motion: reduce) { .app { transition: none; } }
</style>
