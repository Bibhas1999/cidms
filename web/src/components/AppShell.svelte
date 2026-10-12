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
  import NotificationBell from "./NotificationBell.svelte";
  import Credit from "./Credit.svelte";
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

  // Phones and tablets: the sidebar is a drawer. Esc closes it; the page behind doesn't scroll while it's open.
  $effect(() => {
    if (!navOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") navOpen = false; };
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
<div class="app" class:nav-open={navOpen}>
  <aside class="sidebar" aria-label="Main navigation">
    <div class="sidebar-brand">
      {#if !session.isPlatform && ws?.wordmark_url}
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
          <a class="nav-link" class:is-active={isCurrent(item.href)} href={item.href} aria-current={isCurrent(item.href) ? "page" : undefined}>
            <Icon name={item.icon} /><span>{item.label}</span>
          </a>
        {/each}
      {/each}
    </nav>
    <div class="sidebar-footer"><Credit /><a class="terms-link" href="/terms">Terms</a></div>
  </aside>
  {#if navOpen}<button class="nav-backdrop" type="button" aria-label="Close menu" onclick={() => (navOpen = false)}></button>{/if}

  <div class="main">
    <header class="topbar">
      <button class="btn btn-ghost btn-icon menu-toggle" type="button" aria-label={navOpen ? "Close menu" : "Open menu"} use:tooltip={navOpen ? "Close menu" : "Open menu"}
              aria-expanded={navOpen} onclick={() => (navOpen = !navOpen)}><Icon name="menu" /></button>
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
</style>
