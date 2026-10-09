<script lang="ts">
  let { embedded = false }: { embedded?: boolean; params?: Record<string, string> } = $props();
  import Icon from "../components/Icon.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import Pagination from "../components/Pagination.svelte";
  import { get } from "../lib/api";
  import { actionLabel, dateTime } from "../lib/format";
  import { router, setQuery } from "../lib/router.svelte";
  import type { Activity, Page } from "../lib/types";

  const SIZE = $derived(Math.min(100, Number(router.query.get("size")) || 50));
  const page = $derived(Number(router.query.get("page") ?? 1) || 1);
  const action = $derived(router.query.get("action") ?? "");

  let data = $state<Page<Activity> | null>(null);
  let loadError = $state("");

  const FILTERS = [
    ["", "Everything"], ["user.", "Sign-ins, sign-outs and passwords"], ["user.sign_in_failed", "Failed sign-ins"],
    ["bill.", "Bills"], ["payment.", "Payments and refunds"], ["patient.", "Patients"], ["catalogue.", "Tests, prices and doctors"],
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

<PageHeader compact={embedded} eyebrow="Administration" title="Activity log" description="Every sign-in and change, with who did it, when and from where. Nothing here can be edited." />

<section class="card">
  <div class="toolbar">
    <label class="label" for="action">Show</label>
    <select id="action" class="select" value={action} onchange={(e) => setQuery({ action: e.currentTarget.value, page: null })}>
      {#each FILTERS as [value, label] (value)}<option {value}>{label}</option>{/each}
    </select>
  </div>
  {#if loadError}
    <div class="card-content"><div class="alert alert-destructive" role="alert"><Icon name="alert" />{loadError}</div></div>
  {:else if data}
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>When</th><th>Who</th><th>What</th><th>Details</th><th>From</th></tr></thead>
        <tbody>
          {#each data.items as a (a.id)}
            <tr>
              <td class="nowrap text-sm">{dateTime(a.created_at)}</td>
              <td class="cell-title">{a.user_name ?? "—"}</td>
              <td>{actionLabel(a.action)}</td>
              <td class="cell-sub" style="max-width: 420px; overflow-wrap: anywhere">{summary(a.details)}</td>
              <td class="mono">{a.ip_address ?? ""}</td>
            </tr>
          {:else}
            <tr><td colspan="5"><div class="empty"><Icon name="inbox" />Nothing recorded yet.</div></td></tr>
          {/each}
        </tbody>
      </table>
    </div>
    {#if data.total > 0}<Pagination page={data.page} size={data.size} total={data.total} onchange={(p) => setQuery({ page: p }, { replace: false })} />{/if}
  {:else}
    <div class="empty" aria-busy="true">Loading…</div>
  {/if}
</section>
