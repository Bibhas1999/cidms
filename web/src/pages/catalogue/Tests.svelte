<script lang="ts">
  import { z } from "zod";
  import Button from "../../components/Button.svelte";
  import BulkAddDialog from "../../components/BulkAddDialog.svelte";
  import DataTable from "../../components/DataTable.svelte";
  import Dialog from "../../components/Dialog.svelte";
  import Field from "../../components/Field.svelte";
  import FilterBar from "../../components/FilterBar.svelte";
  import FormErrors from "../../components/FormErrors.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import StatusBadge from "../../components/StatusBadge.svelte";
  import type { RowAction } from "../../components/RowMenu.svelte";
  import { get, post, put } from "../../lib/api";
  import { Form } from "../../lib/form.svelte";
  import { rupees } from "../../lib/format";
  import { router, setQuery } from "../../lib/router.svelte";
  import { money, optionalText, submitting, text } from "../../lib/schemas";
  import { session } from "../../lib/session.svelte";
  import { notify, notifyError } from "../../lib/toast.svelte";
  import type { Department, LabTest, Page, TestType } from "../../lib/types";
  import DepartmentsTab from "./DepartmentsTab.svelte";
  import TestTypesTab from "./TestTypesTab.svelte";

  const TABS = [{ key: "tests", label: "Tests" }, { key: "departments", label: "Departments" }, { key: "types", label: "Test types" }] as const;

  const SIZE = $derived(Math.min(100, Number(router.query.get("size")) || 25));
  const tab = $derived(TABS.find((t) => t.key === router.query.get("tab"))?.key ?? "tests");
  const page = $derived(Number(router.query.get("page") ?? 1) || 1);
  const search = $derived(router.query.get("search") ?? "");
  const department = $derived(router.query.get("department") ?? "");
  const showOff = $derived(router.query.get("all") === "1");
  const canManage = $derived(session.can("catalogue.manage"));

  let data = $state<Page<LabTest> | null>(null);
  let loadError = $state("");
  let loading = $state(false);
  let reload = $state(0);

  let departments = $state<Department[]>([]);
  let types = $state<TestType[]>([]);
  let listsLoaded = $state(false);
  let listsReload = $state(0);

  $effect(() => {
    if (tab !== "tests") return;
    const ctrl = new AbortController();
    const query = { page, size: SIZE, search, department_id: department, active: showOff ? undefined : "true" };
    reload;
    loading = true;
    get<Page<LabTest>>("/api/tests", query, ctrl.signal)
      .then((d) => { data = d; loadError = ""; })
      .catch((e) => { if (e.name !== "AbortError") loadError = e.message; })
      .finally(() => { loading = false; });
    return () => ctrl.abort();
  });

  $effect(() => {
    listsReload;
    Promise.all([get<Department[]>("/api/departments"), get<TestType[]>("/api/test-types")])
      .then(([d, t]) => { departments = d; types = t; listsLoaded = true; })
      .catch((e) => notifyError(e));
  });

  function listsChanged() {
    listsReload++;
    reload++; // test rows carry their department and type names
  }

  function chooseTab(key: string) {
    setQuery({ tab: key === "tests" ? null : key, page: null, search: null, department: null, all: null });
  }

  // ---------- add / edit a test ----------
  const schema = z.object({
    name: text("Enter the test's name.", 200, 2),
    code: optionalText(20),
    department_id: z.string().min(1, "Choose the department."),
    test_type_id: z.string(),
    price: money("Enter the price."),
    is_active: z.boolean(),
  });
  const labels = { name: "Name", code: "Short code", department_id: "Department", test_type_id: "Type", price: "Price" };

  let dialogOpen = $state(false);
  let bulkOpen = $state(false);
  let editing = $state<LabTest | null>(null);
  const form = new Form({
    schema, initial: { name: "", code: "", department_id: "", test_type_id: "", price: null as number | null, is_active: true },
    onSubmit: async (v) => {
      const body = { name: v.name, code: v.code, department_id: v.department_id || null, test_type_id: v.test_type_id || null,
                     price: Number(v.price).toFixed(2), is_active: v.is_active };
      if (editing) await put(`/api/tests/${editing.id}`, body);
      else await post("/api/tests", body);
      notify(editing ? `${v.name} saved.` : `${v.name} added at ${rupees(Number(v.price))}.`);
      dialogOpen = false;
      reload++;
    },
  });

  // A switched-off department or type stays offered when the test already uses it.
  const deptOptions = $derived(departments.filter((d) => d.is_active || d.id === form.values.department_id));
  const typeOptions = $derived(types.filter((t) => t.is_active || t.id === form.values.test_type_id));


  function openEdit(t: LabTest) {
    editing = t;
    form.reset({ name: t.name, code: t.code, department_id: t.department.id, test_type_id: t.test_type?.id ?? "", price: Number(t.price), is_active: t.is_active });
    dialogOpen = true;
  }

  async function setActive(t: LabTest, on: boolean) {
    try {
      await put(`/api/tests/${t.id}`, { name: t.name, code: t.code, department_id: t.department.id, test_type_id: t.test_type?.id ?? null,
                                        price: t.price, is_active: on });
      notify(on ? `${t.name} switched on.` : `${t.name} switched off. It can't be added to new bills.`);
      reload++;
    } catch (e) {
      notifyError(e, { title: "Couldn't change it" });
    }
  }

  function actionsFor(t: LabTest): RowAction[] {
    if (!canManage) return [];
    return [
      { label: "Edit", icon: "edit", onclick: () => openEdit(t), hint: "Name, code, department, type or price" },
      t.is_active
        ? { label: "Switch off", icon: "lock", tone: "danger", onclick: () => setActive(t, false), hint: "Can't be added to new bills; old bills keep it" }
        : { label: "Switch on", icon: "check", onclick: () => setActive(t, true) },
      { label: "Bills with this test", icon: "receipt", href: `/bills?test_id=${t.id}&test=${encodeURIComponent(t.name)}` },
    ];
  }
</script>

{#snippet testCell(t: LabTest)}<div class="cell-title">{t.name}</div>{#if t.code}<div class="cell-sub mono">{t.code}</div>{/if}{/snippet}
{#snippet typeCell(t: LabTest)}
  {#if t.test_type}
    <span class="row-wrap gap-sm type-badges"><span class="badge badge-navy badge-plain">{t.test_type.name}</span>
      {#if t.test_type.is_imaging}<StatusBadge tone="info" label="Imaging" help="Has images: marked scanned on the worklist before it's handed over." />{/if}</span>
  {:else}<span class="text-muted">—</span>{/if}
{/snippet}
{#snippet statusCell(t: LabTest)}<StatusBadge active={t.is_active} help={t.is_active ? "" : "Can't be added to new bills."} />{/snippet}

<PageHeader eyebrow="Catalogue" title="Tests & prices" description="The tests the centre offers, what each costs, and how they're grouped.">
  {#snippet actions()}
    {#if canManage && tab === "tests"}<Button variant="primary" icon="plus" onclick={() => (bulkOpen = true)}>Add tests</Button>{/if}
  {/snippet}
</PageHeader>

<section class="card" aria-label="Tests and prices">
  <div class="tabs" role="tablist" aria-label="Catalogue">
    {#each TABS as t (t.key)}
      <button class="tab" role="tab" aria-selected={tab === t.key} onclick={() => chooseTab(t.key)}>{t.label}</button>
    {/each}
  </div>

  {#if tab === "departments"}
    <DepartmentsTab {departments} loaded={listsLoaded} onchanged={listsChanged} />
  {:else if tab === "types"}
    <TestTypesTab {types} loaded={listsLoaded} onchanged={listsChanged} />
  {:else}
    <FilterBar placeholder="Search by test name or code…" searchLabel="Search tests" inlineKeys={["department", "all"]}>
      {#snippet inline()}
        <label class="sr-only" for="department">Department</label>
        <select id="department" class="select" value={department} onchange={(e) => setQuery({ department: e.currentTarget.value, page: null })}>
          <option value="">All departments</option>
          {#each departments as d (d.id)}<option value={d.id}>{d.name}{d.is_active ? "" : " (switched off)"}</option>{/each}
        </select>
        <label class="check-row">
          <input class="checkbox" type="checkbox" checked={showOff} onchange={(e) => setQuery({ all: e.currentTarget.checked ? "1" : null, page: null })} />
          <span>Show switched-off</span>
        </label>
      {/snippet}
    </FilterBar>
    <DataTable label="Tests" rows={data?.items ?? []} {loading} error={loadError} onretry={() => reload++} page={data}
               actions={canManage ? actionsFor : undefined} actionsLabel={(t) => `Actions for ${t.name}`} onrowclick={canManage ? openEdit : undefined}
               empty={{ icon: "flask", title: search || department ? "No test matches these filters." : "No tests yet." }}
               columns={[
                 { key: "test", label: "Test", cell: testCell, mobile: "title" },
                 { key: "dept", label: "Department", value: (t) => t.department.name, mobile: "sub" },
                 { key: "type", label: "Type", cell: typeCell, optional: true },
                 { key: "price", label: "Price", value: (t) => rupees(t.price), align: "right", class: "money", mobile: "end",
                   tip: "The price for new bills. Changing it doesn't change bills already made." },
                 { key: "status", label: "Status", cell: statusCell },
               ]} />
  {/if}
</section>

<Dialog bind:open={dialogOpen} title={editing ? `Edit ${editing.name}` : "Add a test"} icon={editing ? "edit" : "flask"} tone="info"
        description={editing ? "A new price applies to new bills. Bills already made keep the price they were billed at." : ""}>
  <form id="test-form" class="stack" onsubmit={submitting(form, "Couldn't save")} novalidate>
    <FormErrors {form} {labels} idPrefix="t_" />
    <div class="form-grid">
      <Field id="t_name" label="Name" required error={form.error("name")} tip="As it prints on the bill and the report.">
        {#snippet children({ invalid, describedby })}
          <input id="t_name" class="input" autocomplete="off" bind:value={form.values.name} {...form.field("name")} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
      <Field id="t_code" label="Short code" optional error={form.error("code")} tip="A few letters the front desk can type to find the test quickly, e.g. CBC or USG-WA.">
        {#snippet children({ invalid, describedby })}
          <input id="t_code" class="input mono" maxlength="20" bind:value={form.values.code} {...form.field("code")} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
      <Field id="t_department_id" label="Department" required error={form.error("department_id")}
             tip="Which section of the centre does the test. Bills and reports can be filtered by department.">
        {#snippet children({ invalid, describedby })}
          <select id="t_department_id" class="select" bind:value={form.values.department_id} {...form.field("department_id")} aria-invalid={invalid} aria-describedby={describedby}>
            <option value="" disabled>Choose…</option>
            {#each deptOptions as d (d.id)}<option value={d.id}>{d.name}</option>{/each}
          </select>
        {/snippet}
      </Field>
      <Field id="t_test_type_id" label="Type" optional error={form.error("test_type_id")}
             tip="Types with images (X-ray, CT, MRI, USG) go through scanning on the worklist before the report is handed over.">
        {#snippet children({ invalid, describedby })}
          <select id="t_test_type_id" class="select" bind:value={form.values.test_type_id} {...form.field("test_type_id")} aria-invalid={invalid} aria-describedby={describedby}>
            <option value="">No type</option>
            {#each typeOptions as t (t.id)}<option value={t.id}>{t.name}{t.is_imaging ? " (has images)" : ""}</option>{/each}
          </select>
        {/snippet}
      </Field>
      <Field id="t_price" label="Price (₹)" required error={form.error("price")}
             tip="What the patient pays for one of this test, before any discount. A new price only applies to new bills.">
        {#snippet children({ invalid, describedby })}
          <input id="t_price" class="input money" type="number" min="0" step="0.01" inputmode="decimal" bind:value={form.values.price}
                 {...form.field("price")} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
    </div>
    <label class="check-row check-top">
      <input class="checkbox" type="checkbox" bind:checked={form.values.is_active} />
      <span><span class="font-semibold">Active</span> <span class="text-muted">· switched-off tests can't be added to new bills.</span></span>
    </label>
  </form>
  {#snippet footer()}
    <Button onclick={() => (dialogOpen = false)}>Cancel</Button>
    <Button variant="primary" type="submit" form="test-form" loading={form.submitting} loadingText="Saving…">{editing ? "Save changes" : "Add test"}</Button>
  {/snippet}
</Dialog>

<BulkAddDialog bind:open={bulkOpen} kind="tests" {departments} {types} onadded={() => reload++} />

<style>
  .type-badges { flex-wrap: wrap; }
  @media (max-width: 640px) { .type-badges { justify-content: flex-end; } }
</style>
