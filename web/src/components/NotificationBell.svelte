<script lang="ts">
  import { exactTime, notifications, relativeTime, SEVERITY_ICON, type Notice } from "../lib/notifications.svelte";
  import { tooltip } from "../lib/tooltip";
  import EmptyState from "./EmptyState.svelte";
  import Icon from "./Icon.svelte";
  import IconButton from "./IconButton.svelte";

  // The bell in the top bar: the unread count, and a list of the latest notifications. On phones the list opens
  // as a sheet from the bottom of the screen. Starts the live stream when it's shown (only for signed-in people).
  let open = $state(false);
  let button = $state<HTMLButtonElement>();
  let panel = $state<HTMLElement>();
  let now = $state(Date.now());

  $effect(() => {
    notifications.start();
    const clock = setInterval(() => (now = Date.now()), 60_000);
    return () => { clearInterval(clock); notifications.stop(); };
  });

  $effect(() => {
    if (!open) return;
    now = Date.now();
    void notifications.refresh();
    const onClick = (e: MouseEvent) => {
      if (!panel?.contains(e.target as Node) && !button?.contains(e.target as Node)) open = false;
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { open = false; button?.focus(); } };
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("click", onClick); document.removeEventListener("keydown", onKey); };
  });

  const label = $derived(notifications.unread ? `Notifications, ${notifications.unread} unread` : "Notifications");
  const badge = $derived(notifications.unread > 99 ? "99+" : String(notifications.unread));

  function follow(n: Notice) {
    void notifications.markRead(n.id);
    open = false;
  }
</script>

<div class="popover-anchor">
  <button class="btn btn-ghost icon-button" type="button" bind:this={button} aria-label={label} aria-haspopup="true" aria-expanded={open}
          use:tooltip={{ text: label, placement: "bottom" }} onclick={() => (open = !open)}>
    <Icon name="bell" />
    {#if notifications.unread}<span class="bell-count" aria-hidden="true">{badge}</span>{/if}
  </button>
  {#if open}
    <button class="sheet-backdrop" type="button" aria-label="Close notifications" onclick={() => (open = false)}></button>
    <section class="popover notif-popover" aria-label="Notifications" bind:this={panel}>
      <div class="popover-head">
        <h2 class="popover-title font-semibold">Notifications</h2>
        <div class="row" style="gap: 4px">
          {#if notifications.unread}
            <IconButton icon="check" size="sm" label="Mark all as read" onclick={() => notifications.markAllRead()} />
          {/if}
          <IconButton icon="settings" size="sm" label="Notification settings" href="/settings/notifications" onclick={() => (open = false)} />
        </div>
      </div>
      <div class="notif-list">
        {#if !notifications.loaded}
          <p class="notif-empty text-sm text-muted">Loading…</p>
        {:else if !notifications.items.length}
          <EmptyState icon="bell" title="You're all caught up." text="Bills cancelled, reports signed, daily summaries and exports show up here." compact />
        {:else}
          <ul class="notif-items">
            {#each notifications.items as n (n.id)}
              <li class="notif-row">
                <a class="notif-item" class:is-unread={!n.read_at} href={n.link || "/notifications"} onclick={() => follow(n)}>
                  <span class="sev sev-{n.severity}" aria-hidden="true"><Icon name={SEVERITY_ICON[n.severity]} size="sm" /></span>
                  <span class="grow">
                    <span class="notif-title">{n.title}</span>
                    {#if n.body}<span class="notif-body">{n.body}</span>{/if}
                    <span class="notif-time" use:tooltip={exactTime(n.created_at)}>{relativeTime(n.created_at, now)}</span>
                  </span>
                  {#if !n.read_at}<span class="unread-dot" aria-label="Unread"></span>{/if}
                </a>
                {#if !n.read_at}
                  <span class="row-action"><IconButton icon="check" size="sm" label="Mark as read" onclick={() => notifications.markRead(n.id)} /></span>
                {/if}
              </li>
            {/each}
          </ul>
        {/if}
      </div>
      <div class="popover-foot"><a class="dd-sub text-sm" href="/notifications" onclick={() => (open = false)}>See all notifications</a></div>
    </section>
  {/if}
</div>

<style>
  .notif-row { position: relative; }
  .notif-row .notif-item { padding-right: 44px; }
  .row-action { position: absolute; right: 6px; top: 8px; opacity: 0; transition: opacity .12s; }
  .notif-row:hover .row-action, .row-action:focus-within { opacity: 1; }
  .notif-time { align-self: flex-start; }
  .sev { flex: none; width: 28px; height: 28px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center;
         background: var(--muted); color: var(--muted-foreground); }
  .sev-success { background: color-mix(in srgb, #15803d 14%, transparent); color: #15803d; }
  .sev-warning { background: color-mix(in srgb, #b45309 14%, transparent); color: #b45309; }
  .sev-danger { background: color-mix(in srgb, var(--destructive) 14%, transparent); color: var(--destructive); }
  .sheet-backdrop { display: none; }
  @media (hover: none) { .row-action { opacity: 1; } }
  @media (max-width: 640px) {
    .sheet-backdrop { display: block; position: fixed; inset: 0; z-index: 59; background: rgb(0 0 0 / .35); border: 0; }
    .notif-popover { position: fixed; left: 0; right: 0; bottom: 0; top: auto; width: 100%; max-width: 100%;
                     border-radius: var(--radius-lg) var(--radius-lg) 0 0; max-height: 85vh; display: flex; flex-direction: column;
                     padding-bottom: env(safe-area-inset-bottom); animation: sheet-up .2s ease-out; }
    .notif-popover .notif-list { max-height: none; flex: 1; }
  }
</style>
