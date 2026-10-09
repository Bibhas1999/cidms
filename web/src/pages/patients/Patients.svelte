<script lang="ts">
  import Icon from "../../components/Icon.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import Pagination from "../../components/Pagination.svelte";
  import { get } from "../../lib/api";
  import { date } from "../../lib/format";
  import { navigate, router, setQuery } from "../../lib/router.svelte";
  import { session } from "../../lib/session.svelte";
  import { ageGender, type Page, type Patient } from "../../lib/types";

  const SIZE = $derived(Math.min(100, Number(router.query.get("size")) || 25));
  const page = $derived(Number(router.query.get("page") ?? 1) || 1);
  const search = $derived(router.query.get("search") ?? "");

  let data = $state<Page<Patient> | null>(null);
  let loadError = $state("");
  let loading = $state(false);
  let reload = $state(0);
  let searchText = $state(router.query.get("search") ?? "");

  $effect(() => {
    const ctrl = new AbortController();
    const query = { page, size: SIZE, search };
    reload;
    loading = true;
    get<Page<Patient>>("/api/patients", query, ctrl.signal)
      .then((d) => { data = d; loadError = ""; })
      .catch((e) => { if (e.name !== "AbortError") loadError = e.message; })
      .finally(() => { loading = false; });
    return () => ctrl.abort();
  });

  let searchTimer: ReturnType<typeof setTimeout>;
  function onSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => setQuery({ search: searchText.trim(), page: null }), 300);
  }

  function openRow(e: MouseEvent, id: string) {
    // Let real links and selected text behave normally; anywhere else on the row opens the patient.
    if ((e.target as Element).closest("a, button") || window.getSelection()?.toString()) return;
    navigate(`/patients/${id}`);
  }
</script>

<PageHeader eyebrow="Front desk" title="Patients" description="Everyone who has been billed at the centre. Open a patient to see their details and bills.">
  {#snippet actions()}
    {#if session.can("billing.create")}<a class="btn btn-primary" href="/bills/new"><Icon name="plus" /> New bill</a>{/if}
  {/snippet}
</PageHeader>

<section class="card">
  <div class="toolbar">
    <div class="input-group">
      <Icon name="search" />
      <label class="sr-only" for="search">Search patients</label>
      <input id="search" class="input" type="search" placeholder="Search by name, mobile or patient number…" bind:value={searchText} oninput={onSearch} />
    </div>
  </div>

  {#if loadError}
    <div class="card-content"><div class="alert alert-destructive" role="alert"><Icon name="alert" /><div>{loadError} <button class="link-button" onclick={() => reload++}>Try again</button></div></div></div>
  {:else if data}
    <div class="table-wrap" aria-busy={loading}>
      <table class="table">
        <thead><tr><th>Patient</th><th>Age / gender</th><th>Mobile</th><th>Address</th><th>Registered</th></tr></thead>
        <tbody>
          {#each data.items as p (p.id)}
            <tr class="clickable" onclick={(e) => openRow(e, p.id)}>
              <td><div class="cell-title"><a href="/patients/{p.id}">{p.name}</a></div><div class="cell-sub mono">{p.patient_no}</div></td>
              <td>{ageGender(p)}</td>
              <td class="tabular">{p.mobile || "—"}</td>
              <td class="address"><div class="truncate" title={p.address}>{p.address || "—"}</div></td>
              <td class="text-sm nowrap">{date(p.created_at)}</td>
            </tr>
          {:else}
            <tr><td colspan="5"><div class="empty"><Icon name="users" />{search ? "No patient matches that search." : "No patients yet. They're added when their first bill is made."}</div></td></tr>
          {/each}
        </tbody>
      </table>
    </div>
    {#if data.total > 0}<Pagination page={data.page} size={data.size} total={data.total} onchange={(p) => setQuery({ page: p }, { replace: false })} />{/if}
  {:else}
    <div class="empty" aria-busy="true">Loading…</div>
  {/if}
</section>

<style>
  .clickable { cursor: pointer; }
  .address { max-width: 280px; }
</style>
