<script lang="ts">
  import EmptyState from "../components/EmptyState.svelte";
  import Icon from "../components/Icon.svelte";
  import IconButton from "../components/IconButton.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import Pagination from "../components/Pagination.svelte";
  import { get } from "../lib/api";
  import { exactTime, notifications, relativeTime, SEVERITY_ICON, type Notice, type Preferences } from "../lib/notifications.svelte";
  import { router, setQuery } from "../lib/router.svelte";
  import { notifyError } from "../lib/toast.svelte";
  import { tooltip } from "../lib/tooltip";
  import type { Page } from "../lib/types";

  // Every notification for the signed-in person, newest first: All / Unread, by kind and by importance.
  // Filters and the page live in the address (?unread=1&kind=bill.cancelled&page=2), so a view can be bookmarked.
  const q = $derived(router.query);
  const page = $derived(Math.max(1, Number(q.get("page") ?? 1) || 1));
  const size = $derived(Math.min(100, Math.max(1, Number(q.get("size") ?? 25) || 25)));
  const unreadOnly = $derived(q.get("unread") === "1");
  const kind = $derived(q.get("kind") ?? "");
  const severity = $derived(q.get("severity") ?? "");

  let data = $state<Page<Notice> | null>(null);
  let loading = $state(true);
  let kinds = $state<{ code: string; label: string }[]>([]);
  let reload = $state(0);
  const now = Date.now();

  $effect(() => {
    get<Preferences>("/api/notifications/preferences").then((p) => (kinds = p.kinds.map(({ code, label }) => ({ code, label })))).catch(() => {});
  });

  $effect(() => {
    const args = { page, size, unread: unreadOnly ? true : undefined, kind, severity };
    void reload;
    void notifications.unread; // a new one arriving refreshes the list
    const ctrl = new AbortController();
    loading = true;
    get<Page<Notice>>("/api/notifications", args, ctrl.signal)
      .then((d) => { data = d; })
      .catch((e) => { if ((e as Error).name !== "AbortError") notifyError(e, { title: "Couldn't load notifications" }); })
      .finally(() => { loading = false; });
    return () => ctrl.abort();
  });

  async function read(n: Notice) {
    n.read_at = new Date().toISOString();
    await notifications.markRead(n.id);
  }

  async function readAll() {
    try {
      await notifications.markAllRead();
      reload++;
    } catch (e) {
      notifyError(e, { title: "Couldn't mark them as read" });
    }
  }

  const filtered = $derived(unreadOnly || !!kind || !!severity);
</script>

<PageHeader eyebrow="Inbox" title="Notifications" description="What happened at the centre that you should know about. Kept for 90 days after you read them."
            tip="Choose which kinds you get, and turn on browser pop-ups, in Settings > Notifications.">
  {#snippet actions()}
    <a class="btn btn-outline" href="/settings/notifications"><Icon name="settings" /> Settings</a>
    <button class="btn btn-outline" type="button" disabled={!notifications.unread} onclick={readAll}
            use:tooltip={notifications.unread ? `Mark all ${notifications.unread} unread as read` : "Nothing unread"}>
      <Icon name="check" /> Mark all as read</button>
  {/snippet}
</PageHeader>

<section class="card">
  <div class="card-header notif-filters">
    <div class="tabs" role="tablist" aria-label="Show">
      <button class="tab" role="tab" type="button" aria-selected={!unreadOnly} class:is-active={!unreadOnly}
              onclick={() => setQuery({ unread: null, page: null })}>All</button>
      <button class="tab" role="tab" type="button" aria-selected={unreadOnly} class:is-active={unreadOnly}
              onclick={() => setQuery({ unread: "1", page: null })}>Unread{#if notifications.unread} <span class="badge badge-plain">{notifications.unread}</span>{/if}</button>
    </div>
    <div class="row-wrap" style="gap: 8px">
      <label class="sr-only" for="nf-kind">Kind</label>
      <select id="nf-kind" class="select select-sm" value={kind} onchange={(e) => setQuery({ kind: e.currentTarget.value, page: null })}>
        <option value="">Every kind</option>
        {#each kinds as k (k.code)}<option value={k.code}>{k.label}</option>{/each}
      </select>
      <label class="sr-only" for="nf-sev">Importance</label>
      <select id="nf-sev" class="select select-sm" value={severity} onchange={(e) => setQuery({ severity: e.currentTarget.value, page: null })}>
        <option value="">Any importance</option>
        <option value="danger">Problems</option>
        <option value="warning">Warnings</option>
        <option value="success">Good news</option>
        <option value="info">Information</option>
      </select>
      {#if filtered}<button class="btn btn-ghost btn-sm" type="button" onclick={() => setQuery({ unread: null, kind: null, severity: null, page: null })}>Clear</button>{/if}
    </div>
  </div>

  {#if loading && !data}
    <p class="notif-empty text-sm text-muted">Loading…</p>
  {:else if !data?.items.length}
    <EmptyState icon="bell" title={filtered ? "No notifications match these filters." : "No notifications yet."}
                text={filtered ? "Try All, or another kind." : "Cancelled bills, signed reports, exports and daily summaries show up here."} />
  {:else}
    <ul class="notif-items notif-page-list" aria-busy={loading}>
      {#each data.items as n (n.id)}
        <li class="notif-row">
          <a class="notif-item" class:is-unread={!n.read_at} href={n.link || undefined} onclick={() => read(n)}>
            <span class="sev sev-{n.severity}" aria-hidden="true"><Icon name={SEVERITY_ICON[n.severity]} size="sm" /></span>
            <span class="grow">
              <span class="notif-title">{n.title}</span>
              {#if n.body}<span class="notif-body full">{n.body}</span>{/if}
              <span class="notif-time" use:tooltip={exactTime(n.created_at)}>{relativeTime(n.created_at, now)}</span>
            </span>
            {#if !n.read_at}<span class="unread-dot" aria-label="Unread"></span>{/if}
          </a>
          {#if !n.read_at}<span class="row-action"><IconButton icon="check" size="sm" label="Mark as read" onclick={() => read(n)} /></span>{/if}
        </li>
      {/each}
    </ul>
    <Pagination {page} {size} total={data.total} onchange={(p) => setQuery({ page: p }, { replace: false })} />
  {/if}
</section>

<style src="./styles/Notifications.css"></style>
