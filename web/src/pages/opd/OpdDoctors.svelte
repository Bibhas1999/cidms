<script lang="ts">
  import { z } from "zod";
  import Button from "../../components/Button.svelte";
  import DataTable from "../../components/DataTable.svelte";
  import Field from "../../components/Field.svelte";
  import FilterBar from "../../components/FilterBar.svelte";
  import FormDialog from "../../components/FormDialog.svelte";
  import FormErrors from "../../components/FormErrors.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import StatusBadge from "../../components/StatusBadge.svelte";
  import type { RowAction } from "../../components/RowMenu.svelte";
  import { ApiError, get, post, put } from "../../lib/api";
  import { area } from "../../lib/area.svelte";
  import { Form } from "../../lib/form.svelte";
  import { rupees } from "../../lib/format";
  import { router, setQuery } from "../../lib/router.svelte";
  import { money, optionalText, referrerName, submitting } from "../../lib/schemas";
  import { session } from "../../lib/session.svelte";
  import { notify, notifyError } from "../../lib/toast.svelte";
  import type { OpdDoctor } from "../../lib/types";

  // The doctors who see patients in the OPD, each with their consultation fee (filled in on a new visit).
  // Separate from "Doctors & hospitals", which are the doctors who refer patients for tests.
  const FEE_MAX = 100000;
  const search = $derived((router.query.get("search") ?? "").trim().toLowerCase());
  const showOff = $derived(router.query.get("all") === "1");
  const canManage = $derived(session.can("appointments.manage") || session.can("catalogue.manage"));

  let doctors = $state<OpdDoctor[] | null>(null);
  let loadError = $state("");
  let loading = $state(false);
  let reload = $state(0);

  $effect(() => {
    const ctrl = new AbortController();
    const query = { all: showOff ? "true" : undefined };
    reload;
    loading = true;
    get<OpdDoctor[]>("/api/opd/doctors", query, ctrl.signal)
      .then((d) => { doctors = d; loadError = ""; })
      .catch((e) => { if (e.name !== "AbortError") loadError = e.message; })
      .finally(() => { loading = false; });
    return () => ctrl.abort();
  });

  const rows = $derived((doctors ?? []).filter((d) => !search || d.name.toLowerCase().includes(search) || d.qualification.toLowerCase().includes(search)));

  // ---------- add / edit ----------
  const schema = z.object({
    name: referrerName("Enter the doctor's name."),
    qualification: optionalText(200),
    fee: money("Enter the fee, or 0 for no fee."),
    is_active: z.boolean(),
  });
  const labels = { name: "Name", qualification: "Qualification", fee: "Consultation fee", is_active: "Active" };

  let dialogOpen = $state(false);
  let editing = $state<OpdDoctor | null>(null);
  const form = new Form({
    schema, initial: { name: "", qualification: "", fee: null as number | string | null, is_active: true },
    rules: (v, add) => {
      if (v.fee !== null && v.fee !== "" && Number(v.fee) > FEE_MAX) add("fee", `A fee can't be more than ${rupees(FEE_MAX, { paise: false })}.`);
    },
    onSubmit: async (v) => {
      const body = { ...v, fee: Number(v.fee).toFixed(2) };
      try {
        if (editing) await put(`/api/opd/doctors/${editing.id}`, body);
        else await post("/api/opd/doctors", body);
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) { form.errors = { name: e.message }; return; }
        throw e;
      }
      notify(editing ? `${v.name} saved.` : `${v.name} added to the OPD.`);
      dialogOpen = false;
      reload++;
    },
  });

  function openAdd() {
    editing = null;
    form.reset();
    dialogOpen = true;
  }

  function openEdit(d: OpdDoctor) {
    editing = d;
    form.reset({ name: d.name, qualification: d.qualification, fee: Number(d.fee), is_active: d.is_active });
    dialogOpen = true;
  }

  async function setActive(d: OpdDoctor, on: boolean) {
    try {
      await put(`/api/opd/doctors/${d.id}`, { name: d.name, qualification: d.qualification, fee: d.fee, is_active: on });
      notify(on ? `${d.name} switched on.` : `${d.name} switched off. They can't be chosen for new visits.`);
      reload++;
    } catch (e) {
      notifyError(e, { title: "Couldn't change it" });
    }
  }

  function actionsFor(d: OpdDoctor): RowAction[] {
    return [
      { label: "Edit", icon: "edit", onclick: () => openEdit(d), hint: "Name, qualification and fee" },
      d.is_active
        ? { label: "Switch off", icon: "lock", onclick: () => setActive(d, false), tone: "danger", hint: "Can't be chosen for new visits; past visits keep the name" }
        : { label: "Switch on", icon: "check", onclick: () => setActive(d, true) },
    ];
  }
</script>

{#snippet statusCell(d: OpdDoctor)}<StatusBadge active={d.is_active} help={d.is_active ? "" : "Can't be chosen for new visits."} />{/snippet}

<PageHeader eyebrow={area.current?.kind === "admin" ? "Catalogue" : "OPD"} title="OPD doctors"
            description="The doctors who see patients in the OPD, and each one's consultation fee. The fee is filled in on a new visit."
            tip="Not the same list as Doctors & hospitals: those are the doctors who send patients for tests.">
  {#snippet actions()}
    {#if canManage}<Button variant="primary" icon="plus" onclick={openAdd}>Add a doctor</Button>{/if}
  {/snippet}
</PageHeader>

<section class="card" aria-label="OPD doctors">
  <FilterBar placeholder="Search by name or qualification…" searchLabel="Search OPD doctors" inlineKeys={["all"]} noun="doctors">
    {#snippet inline()}
      <label class="check-row">
        <input class="checkbox" type="checkbox" checked={showOff} onchange={(e) => setQuery({ all: e.currentTarget.checked ? "1" : null })} />
        <span>Show switched-off</span>
      </label>
    {/snippet}
  </FilterBar>
  <DataTable label="OPD doctors" {rows} loading={loading && !doctors} error={loadError} onretry={() => reload++} minWidth={0}
             actions={canManage ? actionsFor : undefined} actionsLabel={(d) => `Actions for ${d.name}`}
             onrowclick={canManage ? openEdit : undefined}
             empty={{ icon: "stethoscope", title: search ? "Nobody matches that search." : "No OPD doctors yet.",
                      text: search || !canManage ? "" : "Add the doctors who see patients here, with their fees." }}
             columns={[
               { key: "name", label: "Name", value: (d) => d.name, class: "cell-title", mobile: "title" },
               { key: "qual", label: "Qualification", value: (d) => d.qualification || "—", mobile: "sub" },
               { key: "fee", label: "Fee", value: (d) => (Number(d.fee) > 0 ? rupees(d.fee) : "No fee"), align: "right", class: "money", nowrap: true,
                 tip: "The consultation fee filled in on a new visit. It can be changed on the visit." },
               { key: "status", label: "Status", cell: statusCell, mobile: "end" },
             ]} />
</section>

<FormDialog bind:open={dialogOpen} title={editing ? `Edit ${editing.name}` : "Add an OPD doctor"} icon={editing ? "edit" : "stethoscope"} tone="info"
            submitLabel={editing ? "Save changes" : "Add doctor"} busy={form.submitting} onsubmit={submitting(form, "Couldn't save")}>
  <FormErrors {form} {labels} idPrefix="od_" />
  <Field id="od_name" label="Name" required error={form.error("name")} tip="As patients and the token slip should show it, e.g. Dr. Kakali Sarkar.">
    {#snippet children({ invalid, describedby })}
      <input id="od_name" class="input" autocomplete="off" bind:value={form.values.name} {...form.field("name")} aria-invalid={invalid} aria-describedby={describedby} />
    {/snippet}
  </Field>
  <div class="form-grid">
    <Field id="od_qualification" label="Qualification" optional error={form.error("qualification")} hint="For example MBBS, MD (Medicine).">
      {#snippet children({ invalid, describedby })}
        <input id="od_qualification" class="input" bind:value={form.values.qualification} {...form.field("qualification")} aria-invalid={invalid} aria-describedby={describedby} />
      {/snippet}
    </Field>
    <Field id="od_fee" label="Consultation fee (₹)" required error={form.error("fee")} hint="0 if there's no fee."
           tip="Filled in when a visit with this doctor is booked, and can be changed there. A fee makes a bill for the visit; 0 makes none.">
      {#snippet children({ invalid, describedby })}
        <input id="od_fee" class="input money" type="number" min="0" max={FEE_MAX} step="0.01" inputmode="decimal" bind:value={form.values.fee}
               {...form.field("fee")} oninput={() => { form.touched.fee = true; form.validate(); }} aria-invalid={invalid} aria-describedby={describedby} />
      {/snippet}
    </Field>
  </div>
  <label class="check-row check-top">
    <input class="checkbox" type="checkbox" bind:checked={form.values.is_active} />
    <span><span class="font-semibold">Active</span> <span class="text-muted">· switched-off doctors can't be chosen for new visits.</span></span>
  </label>
</FormDialog>
