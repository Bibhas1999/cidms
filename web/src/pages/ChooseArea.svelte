<script lang="ts">
  import Button from "../components/Button.svelte";
  import Icon from "../components/Icon.svelte";
  import { area, AREA_INFO } from "../lib/area.svelte";
  import type { Area } from "../lib/types";
  import { router } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";

  // After every sign-in: "Where are you working today?" Every area of the centre has a box (Reception, OPD and each
  // department; Admin for owners and admins). Picking one they work in opens its first page, or the page they were
  // going to (?next=); picking one they don't work in says they aren't permitted. Shown without the menu, like
  // choosing a password. Also opened from "Switch area" in the top bar.

  const next = $derived.by(() => {
    const n = router.query.get("next") ?? "";
    return n.startsWith("/") && !n.startsWith("//") && !n.startsWith("/choose-area") ? n : "";
  });
  const firstName = $derived(session.me?.full_name.split(" ")[0] ?? "");
  let refused = $state<Area | null>(null);

  function pick(a: Area) {
    if (a.allowed === false) { refused = a; return; }
    refused = null;
    area.switchTo(a.key, next);
  }
</script>

<div class="ca-wrap">
  <section class="card ca-card" aria-labelledby="ca-title">
    <div class="card-header"><div>
      <span class="eyebrow">{session.workspace?.name}</span>
      <h1 class="page-title ca-title" id="ca-title">Where are you working today?</h1>
      <p class="card-description">
        {#if area.list.length}
          {firstName ? `${firstName}, pick` : "Pick"} the area you're in. You'll see only its menu and pages{area.canSwitch ? "; switch any time from the top bar" : ""}.
        {:else}
          You haven't been given a place to work yet. Ask your centre's owner or admin.
        {/if}
      </p>
    </div></div>
    <div class="card-content">
      {#if refused}
        <div class="alert alert-destructive ca-refused" role="alert"><Icon name="lock" /><div>
          <div class="alert-title">You're not permitted to work in {refused.name}</div>
          Ask your centre's owner or admin to give you access{area.list.length ? ", or pick one of your areas." : "."}
        </div></div>
      {/if}
      <ul class="ca-grid" role="list">
        {#each area.all as a (a.key)}
          {@const info = AREA_INFO[a.kind]}
          {@const here = area.current?.key === a.key}
          {@const locked = a.allowed === false}
          <li>
            <button type="button" class="ca-option" class:is-current={here} class:is-locked={locked} aria-current={here ? "true" : undefined}
                    aria-describedby={locked ? "ca-locked-note" : undefined} onclick={() => pick(a)}>
              <span class="ca-icon" aria-hidden="true"><Icon name={locked ? "lock" : info.icon} /></span>
              <span class="grow ca-text">
                <span class="ca-name">{a.name}{#if here}<span class="badge badge-success badge-plain ca-here">Working here now</span>{/if}</span>
                <span class="ca-line">{locked ? "Not one of your areas." : info.line}</span>
              </span>
              <Icon name={locked ? "lock" : "chevronRight"} />
            </button>
          </li>
        {/each}
      </ul>
      <span class="sr-only" id="ca-locked-note">You're not permitted to work here.</span>
    </div>
    <div class="card-footer">
      {#if area.current}<Button href="/">Back</Button>{/if}
      <Button variant="ghost" icon="logout" onclick={() => session.logout()}>Sign out</Button>
    </div>
  </section>
</div>

<style>
  .ca-option.is-locked { opacity: .7; border-style: dashed; }
  .ca-option.is-locked .ca-icon { background: var(--muted); color: var(--muted-foreground); }
  .ca-refused { margin-bottom: 14px; }
  .ca-wrap { min-height: 100vh; display: grid; place-items: center; padding: 24px 16px; }
  .ca-card { width: min(720px, 100%); }
  .ca-title { margin-top: 8px; }
  .ca-grid { list-style: none; margin: 0; padding: 0; display: grid; gap: 12px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .ca-option {
    display: flex; align-items: center; gap: 14px; width: 100%; height: 100%; min-height: 96px; padding: 16px;
    text-align: left; font: inherit; color: inherit; cursor: pointer;
    background: var(--card); border: 1px solid var(--border); border-radius: var(--radius-lg);
    transition: border-color .15s, background-color .15s, box-shadow .15s;
  }
  .ca-option:hover { border-color: var(--primary); background: var(--accent); }
  .ca-option:focus-visible { outline: 2px solid var(--ring); outline-offset: 2px; }
  .ca-option.is-current { border-color: var(--primary); }
  .ca-icon {
    flex: none; display: grid; place-items: center; width: 44px; height: 44px; border-radius: 12px;
    background: var(--info-soft); color: var(--primary-text);
  }
  .ca-text { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
  .ca-name { font-weight: 600; font-size: 16px; display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
  .ca-line { font-size: 13px; color: var(--muted-foreground); line-height: 1.4; }
  .ca-here { font-size: 11px; }
  @media (max-width: 640px) {
    .ca-wrap { place-items: start center; padding: 16px; }
    .ca-grid { grid-template-columns: minmax(0, 1fr); }
    .ca-option { min-height: 76px; }
  }
</style>
