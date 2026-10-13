<script lang="ts">
  import { z } from "zod";
  import Button from "../../components/Button.svelte";
  import DataTable from "../../components/DataTable.svelte";
  import Dialog from "../../components/Dialog.svelte";
  import Field from "../../components/Field.svelte";
  import FilterBar from "../../components/FilterBar.svelte";
  import FormErrors from "../../components/FormErrors.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import PhoneInput from "../../components/PhoneInput.svelte";
  import StatusBadge from "../../components/StatusBadge.svelte";
  import type { RowAction } from "../../components/RowMenu.svelte";
  import { get, post, put } from "../../lib/api";
  import { Form } from "../../lib/form.svelte";
  import { formatPhone } from "../../lib/phone";
  import { router, setQuery } from "../../lib/router.svelte";
  import { optionalText, phone, submitting, text } from "../../lib/schemas";
  import { session } from "../../lib/session.svelte";
  import { notify, notifyError } from "../../lib/toast.svelte";
  import type { Doctor, Page } from "../../lib/types";

  const SIZE = $derived(Math.min(100, Number(router.query.get("size")) || 25));
  const page = $derived(Number(router.query.get("page") ?? 1) || 1);
  const search = $derived(router.query.get("search") ?? "");
  const showOff = $derived(router.query.get("all") === "1");
  const canManage = $derived(session.can("catalogue.manage"));

  let data = $state<Page<Doctor> | null>(null);
  let loadError = $state("");
  let loading = $state(false);
  let reload = $state(0);

  $effect(() => {
    const ctrl = new AbortController();
    const query = { page, size: SIZE, search, active: showOff ? undefined : "true" };
    reload;
    loading = true;
    get<Page<Doctor>>("/api/doctors", query, ctrl.signal)
      .then((d) => { data = d; loadError = ""; })
      .catch((e) => { if (e.name !== "AbortError") loadError = e.message; })
      .finally(() => { loading = false; });
    return () => ctrl.abort();
  });

  // ---------- add / edit ----------
  const schema = z.object({
    name: text("Enter the doctor's or hospital's name.", 200, 2),
    qualification: optionalText(200),
    phone: phone(false),
    is_active: z.boolean(),
  });
  const labels = { name: "Name", qualification: "Qualification", phone: "Phone" };

  let dialogOpen = $state(false);
  let editing = $state<Doctor | null>(null);
  const form = new Form({
    schema, initial: { name: "", qualification: "", phone: "", is_active: true },
    onSubmit: async (v) => {
      if (editing) await put(`/api/doctors/${editing.id}`, v);
      else await post("/api/doctors", v);
      notify(editing ? `${v.name} saved.` : `${v.name} added.`);
      dialogOpen = false;
      reload++;
    },
  });

  function openAdd() {
    editing = null;
    form.reset();
    dialogOpen = true;
  }

  function openEdit(d: Doctor) {
    editing = d;
    form.reset({ name: d.name, qualification: d.qualification, phone: d.phone, is_active: d.is_active });
    dialogOpen = true;
  }

  async function setActive(d: Doctor, on: boolean) {
    try {
      await put(`/api/doctors/${d.id}`, { name: d.name, qualification: d.qualification, phone: d.phone, is_active: on });
      notify(on ? `${d.name} switched on.` : `${d.name} switched off. They won't be suggested on new bills.`);
      reload++;
    } catch (e) {
      notifyError(e, { title: "Couldn't change it" });
    }
  }

  function actionsFor(d: Doctor): RowAction[] {
    if (!canManage) return [];
    return [
      { label: "Edit", icon: "edit", onclick: () => openEdit(d) },
      d.is_active
        ? { label: "Switch off", icon: "lock", onclick: () => setActive(d, false), tone: "danger", hint: "Not suggested on new bills; old bills keep the name" }
        : { label: "Switch on", icon: "check", onclick: () => setActive(d, true) },
      { label: "Bills referred", icon: "receipt", href: `/bills?doctor_id=${d.id}&doctor=${encodeURIComponent(d.name)}` },
    ];
  }
</script>

{#snippet statusCell(d: Doctor)}<StatusBadge active={d.is_active} help={d.is_active ? "" : "Not suggested on new bills."} />{/snippet}

<PageHeader eyebrow="Catalogue" title="Doctors & hospitals"
            description="Doctors and hospitals that send patients to the centre. One is added automatically when a new name is typed on a bill.">
  {#snippet actions()}
    {#if canManage}<Button variant="primary" icon="plus" onclick={openAdd}>Add doctor / hospital</Button>{/if}
  {/snippet}
</PageHeader>

<section class="card" aria-label="Doctors and hospitals">
  <FilterBar placeholder="Search by name…" searchLabel="Search doctors and hospitals" inlineKeys={["all"]}>
    {#snippet inline()}
      <label class="check-row">
        <input class="checkbox" type="checkbox" checked={showOff} onchange={(e) => setQuery({ all: e.currentTarget.checked ? "1" : null, page: null })} />
        <span>Show switched-off</span>
      </label>
    {/snippet}
  </FilterBar>
  <DataTable label="Doctors and hospitals" rows={data?.items ?? []} {loading} error={loadError} onretry={() => reload++} page={data}
             actions={canManage ? actionsFor : undefined} actionsLabel={(d) => `Actions for ${d.name}`}
             onrowclick={canManage ? openEdit : undefined}
             empty={{ icon: "stethoscope", title: search ? "Nothing matches that search." : "No doctors or hospitals yet." }}
             columns={[
               { key: "name", label: "Name", value: (d) => d.name, class: "cell-title", mobile: "title" },
               { key: "qual", label: "Qualification", value: (d) => d.qualification || "—", mobile: "sub" },
               { key: "phone", label: "Phone", value: (d) => formatPhone(d.phone) || "—", class: "tabular", nowrap: true },
               { key: "status", label: "Status", cell: statusCell, mobile: "end" },
             ]} />
</section>

<Dialog bind:open={dialogOpen} title={editing ? `Edit ${editing.name}` : "Add doctor / hospital"} icon={editing ? "edit" : "stethoscope"} tone="info">
  <form id="doctor-form" class="stack" onsubmit={submitting(form, "Couldn't save")} novalidate>
    <FormErrors {form} {labels} idPrefix="d_" />
    <Field id="d_name" label="Name" required error={form.error("name")} tip="As it should print on bills, e.g. Dr. Kakali Sarkar.">
      {#snippet children({ invalid, describedby })}
        <input id="d_name" class="input" autocomplete="off" bind:value={form.values.name} {...form.field("name")} aria-invalid={invalid} aria-describedby={describedby} />
      {/snippet}
    </Field>
    <div class="form-grid">
      <Field id="d_qualification" label="Qualification" optional error={form.error("qualification")} hint="For example MBBS, MD.">
        {#snippet children({ invalid, describedby })}
          <input id="d_qualification" class="input" bind:value={form.values.qualification} {...form.field("qualification")} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
      <Field id="d_phone" label="Phone" optional error={form.error("phone")} tip="The doctor's or hospital's number, with its country code. Saved in the international form.">
        {#snippet children({ invalid, describedby })}
          {@const f = form.field("phone")}
          <PhoneInput id="d_phone" bind:value={form.values.phone} {invalid} {describedby} onblur={f.onblur} oninput={f.oninput} />
        {/snippet}
      </Field>
    </div>
    <label class="check-row check-top">
      <input class="checkbox" type="checkbox" bind:checked={form.values.is_active} />
      <span><span class="font-semibold">Active</span> <span class="text-muted">· switched-off names aren't suggested on new bills.</span></span>
    </label>
  </form>
  {#snippet footer()}
    <Button onclick={() => (dialogOpen = false)}>Cancel</Button>
    <Button variant="primary" type="submit" form="doctor-form" loading={form.submitting} loadingText="Saving…">{editing ? "Save changes" : "Add"}</Button>
  {/snippet}
</Dialog>
