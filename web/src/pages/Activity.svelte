<script lang="ts">
  import Pagination from "../components/Pagination.svelte";
  import { get } from "../lib/api";
  import { actionLabel, dateTime } from "../lib/format";
  import { router, setQuery } from "../lib/router.svelte";
  import type { Activity, Page } from "../lib/types";

  const SIZE = 50;
  const page = $derived(Number(router.query.get("page") ?? 1) || 1);
  const action = $derived(router.query.get("action") ?? "");

  let data = $state<Page<Activity> | null>(null);
  let loadError = $state("");

  const FILTERS = [
    ["", "Everything"], ["user.", "Sign-ins, sign-outs and passwords"], ["user.sign_in_failed", "Failed sign-ins"],
    ["staff.", "Staff changes"], ["settings.", "Settings changes"], ["client.", "Client changes"],
  ];

  $effect(() => {
    const ctrl = new AbortController();
    get<Page<Activity>>("/api/activity", { page, size: SIZE, action }, ctrl.signal)
      .then((d) => { data = d; loadError = ""; })
      .catch((e) => { if (e.name !== "AbortError") loadError = e.message; });
    return () => ctrl.abort();
  });

  function summary(details: Record<string, unknown>): string {
    return Object.entries(details)
      .map(([k, v]) => Array.isArray(v) && v.length === 2 ? `${k}: ${JSON.stringify(v[0])} → ${JSON.stringify(v[1])}` : `${k}: ${JSON.stringify(v)}`)
      .join("; ");
  }
</script>

<div class="stack">
  <div class="toolbar">
    <h1 class="grow">Activity log</h1>
    <label class="sr-only" for="action">Show</label>
    <select id="action" value={action} onchange={(e) => setQuery({ action: e.currentTarget.value, page: null })}>
      {#each FILTERS as [value, label]}<option {value}>{label}</option>{/each}
    </select>
  </div>
  <div class="card">
    {#if loadError}
      <div class="alert" role="alert">{loadError}</div>
    {:else if data}
      <div class="table-wrap">
        <table class="data">
          <thead><tr><th>When</th><th>Who</th><th>What</th><th>Details</th><th>From</th></tr></thead>
          <tbody>
            {#each data.items as a (a.id)}
              <tr>
                <td class="nowrap">{dateTime(a.created_at)}</td>
                <td>{a.user_name ?? "—"}</td>
                <td>{actionLabel(a.action)}</td>
                <td class="details">{summary(a.details)}</td>
                <td class="mono">{a.ip_address ?? ""}</td>
              </tr>
            {:else}
              <tr><td colspan="5" class="muted empty">Nothing recorded yet.</td></tr>
            {/each}
          </tbody>
        </table>
      </div>
      <Pagination page={data.page} size={data.size} total={data.total} onchange={(p) => setQuery({ page: p }, { replace: false })} />
    {:else}
      <p class="muted empty">Loading…</p>
    {/if}
  </div>
</div>

<style>
  select { width: auto; }
  .table-wrap { overflow-x: auto; }
  .nowrap { white-space: nowrap; }
  .details { font-size: 13px; color: var(--text-2); max-width: 420px; overflow-wrap: anywhere; }
  .empty { padding: 24px; text-align: center; }
</style>
