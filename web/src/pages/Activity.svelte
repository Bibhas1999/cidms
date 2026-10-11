<script lang="ts">
  let { embedded = false }: { embedded?: boolean; params?: Record<string, string> } = $props();
  import DataTable from "../components/DataTable.svelte";
  import FilterBar from "../components/FilterBar.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import { get } from "../lib/api";
  import { actionLabel, dateTime } from "../lib/format";
  import { router, setQuery } from "../lib/router.svelte";
  import type { Activity, Page } from "../lib/types";

  const SIZE = $derived(Math.min(100, Number(router.query.get("size")) || 50));
  const page = $derived(Number(router.query.get("page") ?? 1) || 1);
  const action = $derived(router.query.get("action") ?? "");

  let data = $state<Page<Activity> | null>(null);
  let loadError = $state("");
  let loading = $state(false);
  let reload = $state(0);

  const FILTERS = [
    ["", "Everything"], ["user.", "Sign-ins, sign-outs and passwords"], ["user.sign_in_failed", "Failed sign-ins"],
    ["bill.", "Bills"], ["payment.", "Payments and refunds"], ["patient.", "Patients"], ["catalogue.", "Tests, prices and doctors"],
    ["staff.", "Staff changes"], ["settings.", "Settings changes"], ["client.", "Client changes"],
  ];

  $effect(() => {
    const ctrl = new AbortController();
    const query = { page, size: SIZE, action };
    reload;
    loading = true;
    get<Page<Activity>>("/api/activity", query, ctrl.signal)
      .then((d) => { data = d; loadError = ""; })
      .catch((e) => { if (e.name !== "AbortError") loadError = e.message; })
      .finally(() => { loading = false; });
    return () => ctrl.abort();
  });

  function summary(details: Record<string, unknown>): string {
    return Object.entries(details)
      .map(([k, v]) => Array.isArray(v) && v.length === 2 ? `${k}: ${JSON.stringify(v[0])} → ${JSON.stringify(v[1])}` : `${k}: ${JSON.stringify(v)}`)
      .join("; ");
  }
</script>

{#snippet detailsCell(a: Activity)}<span class="cell-sub details">{summary(a.details)}</span>{/snippet}

<PageHeader compact={embedded} eyebrow="Administration" title="Activity log" description="Every sign-in and change, with who did it, when and from where. Nothing here can be edited."
            tip="Kept for audits. Entries can't be changed or deleted by anyone, including the owner." />

<section class="card" aria-label="Activity log">
  <FilterBar search={false} inlineKeys={["action"]}>
    {#snippet inline()}
      <label class="sr-only" for="action">Show</label>
      <select id="action" class="select activity-filter" value={action} onchange={(e) => setQuery({ action: e.currentTarget.value, page: null })}>
        {#each FILTERS as [value, label] (value)}<option {value}>{label}</option>{/each}
      </select>
    {/snippet}
  </FilterBar>
  <DataTable label="Activity" rows={data?.items ?? []} {loading} error={loadError} onretry={() => reload++} page={data}
             empty={{ icon: "inbox", title: action ? "Nothing of this kind recorded." : "Nothing recorded yet." }}
             columns={[
               { key: "what", label: "What", value: (a) => actionLabel(a.action), class: "cell-title", mobile: "title" },
               { key: "when", label: "When", value: (a) => dateTime(a.created_at), nowrap: true, class: "text-sm", mobile: "end" },
               { key: "who", label: "Who", value: (a) => a.user_name ?? "—" },
               { key: "details", label: "Details", cell: detailsCell, mobile: "sub" },
               { key: "from", label: "From", value: (a) => a.ip_address ?? "", class: "mono", optional: true,
                 tip: "The network address the change came from." },
             ]} />
</section>

<style>
  .details { display: block; max-width: 420px; overflow-wrap: anywhere; }
  .activity-filter { max-width: none !important; min-width: 240px !important; }
  @media (max-width: 640px) { .details { max-width: none; } .activity-filter { min-width: 0 !important; } }
</style>
