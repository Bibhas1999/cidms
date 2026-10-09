<script lang="ts">
  import type { Snippet } from "svelte";
  import { confirmDialog } from "../lib/confirm.svelte";
  import { CLIENT_NAV, PLATFORM_NAV } from "../lib/nav";
  import { router } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";
  import { applyTheme, getTheme, type Theme } from "../lib/theme";
  import Avatar from "./Avatar.svelte";
  import Icon from "./Icon.svelte";

  // The app frame, laid out like the Sandhata Registry: sidebar with grouped sections, a top bar with
  // breadcrumbs and the profile menu, and the page. `available` = paths that have a page.
  let { title, available, children }: { title: string; available: Set<string>; children: Snippet } = $props();

  const sections = $derived(
    (session.isPlatform ? PLATFORM_NAV : CLIENT_NAV)
      .map((s) => ({ ...s, items: s.items.filter((i) => available.has(i.href) && (!i.permission || session.can(i.permission))) }))
      .filter((s) => s.items.length),
  );
  const isCurrent = (href: string) =>
    href === "/" ? router.path === "/" : router.path === href || (router.path.startsWith(href + "/") && !available.has(router.path));

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

  /** Hand the computer to a colleague: sign out at once and show the accounts used here. */
  async function switchAccount() {
    menuOpen = false;
    await session.logout({ switching: true });
  }

  async function signOut() {
    menuOpen = false;
    if (await confirmDialog({ title: "Sign out of Supreme DMS?", message: "You'll need your email and password to come back.",
                              confirmLabel: "Sign out", tone: "danger" })) await session.logout();
  }
</script>

<a class="skip-link" href="#main">Skip to main content</a>
<div class="app" class:nav-open={navOpen}>
  <aside class="sidebar" aria-label="Main navigation">
    <div class="sidebar-brand">
      <a href="/" class="link-reset row brand-link" style="gap: 10px">
        {#if ws?.logo_url}
          <img class="centre-logo" src={ws.logo_url} alt="" width="34" height="34" />
        {:else}
          <span class="centre-mark"><Icon name="activity" /></span>
        {/if}
        <span class="grow">
          <span class="centre-name truncate" style="display:block">{session.isPlatform ? "Supreme DMS" : ws?.name}</span>
          <span class="centre-sub">{session.isPlatform ? "Platform" : "DMS"}</span>
        </span>
      </a>
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
    {#if !session.isPlatform}<div class="sidebar-footer"><span class="powered">Powered by Supreme DMS</span></div>{/if}
  </aside>
  {#if navOpen}<button class="sr-only" onclick={() => (navOpen = false)}>Close menu</button>{/if}

  <div class="main">
    <header class="topbar">
      <button class="btn btn-ghost btn-icon menu-toggle" type="button" aria-label={navOpen ? "Close menu" : "Open menu"}
              aria-expanded={navOpen} onclick={() => (navOpen = !navOpen)}><Icon name="menu" /></button>
      <nav class="breadcrumbs grow" aria-label="Breadcrumb">
        <a href="/" class="text-muted">{session.isPlatform ? "Platform" : ws?.name}</a>
        <Icon name="chevronRight" size="sm" />
        <strong aria-current="page">{title}</strong>
      </nav>
      {#if local}<span class="badge badge-info badge-plain hide-sm" title="Running on this computer">Local</span>{/if}
      <div class="topbar-actions">
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
                  <div class="font-semibold truncate" title={session.me?.full_name}>{session.me?.full_name}</div>
                  <div class="text-xs text-muted truncate" title={session.me?.email}>{session.me?.email}</div>
                  {#each session.me?.roles ?? [] as role}<span class="badge badge-info badge-plain mt-2">{role}</span>{/each}
                </div>
              </div>
              <fieldset class="theme-switch">
                <legend class="sr-only">Theme</legend>
                <span class="theme-label" aria-hidden="true">Theme</span>
                <div class="theme-icons">
                  {#each [["light", "Light", "sun"], ["dark", "Dark", "moon"], ["system", "Match system", "monitor"]] as [value, label, ic] (value)}
                    <label class="theme-option" title={label}>
                      <input type="radio" name="theme" class="sr-only" {value} checked={theme === value}
                             onchange={() => { theme = value as Theme; applyTheme(theme); }} />
                      <span><Icon name={ic} size="sm" /><span class="sr-only">{label}</span></span>
                    </label>
                  {/each}
                </div>
              </fieldset>
              <div class="profile-signout">
                <a class="btn btn-ghost btn-block menu-item" href="/settings"><Icon name="settings" /> Settings</a>
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
