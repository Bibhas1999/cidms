<script lang="ts">
  import { tooltip } from "../../lib/tooltip";
  import DataTable from "../../components/DataTable.svelte";
  import FilterBar from "../../components/FilterBar.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import type { RowAction } from "../../components/RowMenu.svelte";
  import { get } from "../../lib/api";
  import { date } from "../../lib/format";
  import { formatPhone } from "../../lib/phone";
  import { router } from "../../lib/router.svelte";
  import { session } from "../../lib/session.svelte";
  import { ageGender, type Page, type Patient } from "../../lib/types";

  const SIZE = $derived(Math.min(100, Number(router.query.get("size")) || 25));
  const page = $derived(Number(router.query.get("page") ?? 1) || 1);
  const search = $derived(router.query.get("search") ?? "");

  let data = $state<Page<Patient> | null>(null);
  let loadError = $state("");
  let loading = $state(false);
  let reload = $state(0);

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

  function actionsFor(p: Patient): RowAction[] {
    return [
      { label: "Open patient", icon: "eye", href: `/patients/${p.id}` },
      ...(session.can("billing.create") ? [{ label: "New bill", icon: "plus", href: `/bills/new?patient=${p.id}` }] : []),
      { label: "Their bills", icon: "receipt", href: `/patients/${p.id}#bills` },
    ];
  }
</script>

{#snippet nameCell(p: Patient)}
  <div class="cell-title"><a href="/patients/{p.id}">{p.name}</a></div><div class="cell-sub mono">{p.patient_no}</div>
{/snippet}
{#snippet addressCell(p: Patient)}<div class="truncate address" use:tooltip={p.address}>{p.address || "—"}</div>{/snippet}

<PageHeader eyebrow="Front desk" title="Patients" description="Everyone who has been billed at the centre. Open a patient to see their details and bills." />

<section class="card" aria-label="Patients">
  <FilterBar placeholder="Search by name, mobile or patient number…" searchLabel="Search patients"
             searchTip="Type part of a name, a mobile number (any part) or a patient number." />
  <DataTable label="Patients" rows={data?.items ?? []} {loading} error={loadError} onretry={() => reload++} page={data}
             rowHref={(p) => `/patients/${p.id}`} actions={actionsFor} actionsLabel={(p) => `Actions for ${p.name}`}
             empty={{ icon: "users", title: search ? "No patient matches that search." : "No patients yet.",
                      text: search ? "Check the spelling, or search by mobile number." : "They're added when their first bill is made." }}
             columns={[
               { key: "name", label: "Patient", cell: nameCell, mobile: "title" },
               { key: "age", label: "Age / gender", value: (p) => ageGender(p), mobile: "end" },
               { key: "mobile", label: "Mobile", value: (p) => formatPhone(p.mobile) || "—", class: "tabular", nowrap: true },
               { key: "address", label: "Address", cell: addressCell, optional: true, mobile: "sub" },
               { key: "created", label: "Registered", value: (p) => date(p.created_at), nowrap: true, optional: true, mobile: "hide" },
             ]} />
</section>

<style src="./styles/Patients.css"></style>
