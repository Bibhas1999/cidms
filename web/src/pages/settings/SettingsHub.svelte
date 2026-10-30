<script lang="ts">
  import type { Component } from "svelte";
  import Icon from "../../components/Icon.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import { navigate, router, withNext } from "../../lib/router.svelte";
  import { session } from "../../lib/session.svelte";
  import Activity from "../Activity.svelte";
  import Staff from "../Staff.svelte";
  import Appearance from "./Appearance.svelte";
  import ApiKeys from "./ApiKeys.svelte";
  import Backups from "./Backups.svelte";
  import CentreBackups from "./CentreBackups.svelte";
  import Centre from "./Centre.svelte";
  import NotificationSettings from "./NotificationSettings.svelte";
  import Profile from "./Profile.svelte";

  // Every setting in one place, opened from the profile menu: your own account first, then the centre's
  // (for people allowed to change it). /settings/<section>; the old /staff and /activity addresses land here too.
  let { params = {} }: { params?: Record<string, string> } = $props();

  // A section is either a tab drawn here (`component`), or a plain link elsewhere (`href`) — Password goes to
  // its own page (with its own "confirm the current one" and "signed out everywhere else" wording) rather than
  // a form sitting inside this one, and returns here when it's done.
  interface Section { id: string; label: string; icon: string; group: string; component?: Component<any>; href?: string; show: () => boolean }
  const SECTIONS: Section[] = [
    { id: "profile", label: "My profile", icon: "user", group: "Your account", component: Profile, show: () => true },
    // Only the owner, the centre admin and platform staff change their own password; for everyone else the
    // section simply isn't there (their owner or admin gives them a temporary one from Staff).
    { id: "password", label: "Password", icon: "lock", group: "Your account", href: "/change-password", show: () => !!session.me?.manage_own_account },
    { id: "appearance", label: "Appearance", icon: "sun", group: "Your account", component: Appearance, show: () => true },
    { id: "notifications", label: "Notifications", icon: "bell", group: "Your account", component: NotificationSettings, show: () => true },
    { id: "centre", label: "Centre details", icon: "building", group: "Centre", component: Centre, show: () => !session.isPlatform && session.can("settings.manage") },
    { id: "staff", label: session.isPlatform ? "Platform staff" : "Staff and roles", icon: "shield", group: session.isPlatform ? "Platform" : "Centre", component: Staff,
      show: () => session.can(session.isPlatform ? "platform.staff.manage" : "staff.manage") },
    { id: "activity", label: "Activity log", icon: "activity", group: session.isPlatform ? "Platform" : "Centre", component: Activity,
      show: () => session.can(session.isPlatform ? "platform.activity.view" : "activity.view") },
    { id: "backups", label: "Backups", icon: "download", group: "Platform", component: Backups,
      show: () => session.isPlatform && session.can("platform.backups.manage") },
    { id: "centre-backups", label: "Backups", icon: "download", group: "Centre", component: CentreBackups,
      show: () => !session.isPlatform && session.can("backups.manage") },
    { id: "integrations", label: "API & integrations", icon: "settings", group: "Centre", component: ApiKeys,
      show: () => !session.isPlatform && session.can("integrations.manage") },
  ];

  const visible = $derived(SECTIONS.filter((s) => s.show()));
  const groups = $derived([...new Set(visible.map((s) => s.group))]);
  const tabs = $derived(visible.filter((s) => s.component));
  const wanted = $derived(params.section ?? ({ "/staff": "staff", "/activity": "activity" } as Record<string, string>)[router.path] ?? "profile");
  const current = $derived(tabs.find((s) => s.id === wanted) ?? tabs[0]);

  // An old link to a section that's since become its own page (Password): send it on, same as clicking it here.
  $effect(() => {
    const away = visible.find((s) => s.id === wanted && s.href);
    if (away) navigate(withNext(away.href!, "/settings"), { replace: true });
  });
</script>

<PageHeader eyebrow="Settings" title="Settings" description="Your account, and the centre's settings if you're allowed to change them." />

<div class="settings">
  <nav class="card settings-nav" aria-label="Settings">
    {#each groups as group (group)}
      <div class="nav-heading" role="presentation">{group}</div>
      {#each visible.filter((s) => s.group === group) as s (s.id)}
        <a class="nav-link" class:is-active={current?.id === s.id} href={s.href ? withNext(s.href, "/settings") : `/settings/${s.id}`}
           aria-current={current?.id === s.id ? "page" : undefined}>
          <Icon name={s.icon} /><span>{s.label}</span>
        </a>
      {/each}
    {/each}
  </nav>
  <div class="settings-body">
    {#if current}
      {@const Section = current.component}
      {#key current.id}<Section embedded />{/key}
    {/if}
  </div>
</div>

<style src="./styles/SettingsHub.css"></style>
