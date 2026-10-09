<script lang="ts">
  import Dialog from "../../components/Dialog.svelte";
  import Field from "../../components/Field.svelte";
  import Icon from "../../components/Icon.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import Pagination from "../../components/Pagination.svelte";
  import { ApiError, get, post, put } from "../../lib/api";
  import { rupees } from "../../lib/format";
  import { router, setQuery } from "../../lib/router.svelte";
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
  let searchText = $state(router.query.get("search") ?? "");

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

  let searchTimer: ReturnType<typeof setTimeout>;
  function onSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => setQuery({ search: searchText.trim(), page: null }), 300);
  }

  function chooseTab(key: string) {
    setQuery({ tab: key === "tests" ? null : key, page: null, search: null, department: null, all: null });
    searchText = "";
  }

  // ---------- add / edit a test ----------
  type Form = { name: string; code: string; department_id: string; test_type_id: string; price: number | null; is_active: boolean };
  const blank = (): Form => ({ name: "", code: "", department_id: department, test_type_id: "", price: null, is_active: true });

  let dialogOpen = $state(false);
  let editing = $state<LabTest | null>(null);
  let form = $state<Form>(blank());
  let errors = $state<Record<string, string>>({});
  let saving = $state(false);

  // A switched-off department or type stays offered when the test already uses it.
  const deptOptions = $derived(departments.filter((d) => d.is_active || d.id === form.department_id));
  const typeOptions = $derived(types.filter((t) => t.is_active || t.id === form.test_type_id));

  function openAdd() {
    editing = null;
    form = blank();
    errors = {};
    dialogOpen = true;
  }

  function openEdit(t: LabTest) {
    editing = t;
    form = { name: t.name, code: t.code, department_id: t.department.id, test_type_id: t.test_type?.id ?? "", price: Number(t.price), is_active: t.is_active };
    errors = {};
    dialogOpen = true;
  }

  async function save() {
    saving = true;
    errors = {};
    const body = { name: form.name, code: form.code.trim(), department_id: form.department_id || null,
                   test_type_id: form.test_type_id || null, price: typeof form.price === "number" ? form.price.toFixed(2) : null, is_active: form.is_active };
    try {
      if (editing) await put(`/api/tests/${editing.id}`, body);
      else await post("/api/tests", body);
      notify(editing ? `${form.name} saved.` : `${form.name} added at ${rupees(form.price ?? 0)}.`);
      dialogOpen = false;
      reload++;
    } catch (e) {
      if (e instanceof ApiError && Object.keys(e.fieldErrors).length) errors = e.fieldErrors;
      else notifyError(e, { title: "Couldn't save" });
    } finally {
      saving = false;
    }
  }
</script>

<PageHeader eyebrow="Catalogue" title="Tests & prices" description="The tests the centre offers, what each costs, and how they're grouped.">
  {#snippet actions()}
    {#if canManage && tab === "tests"}<button class="btn btn-primary" onclick={openAdd}><Icon name="plus" /> Add a test</button>{/if}
  {/snippet}
</PageHeader>

<section class="card">
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
    <div class="toolbar">
      <div class="input-group">
        <Icon name="search" />
        <label class="sr-only" for="search">Search tests</label>
        <input id="search" class="input" type="search" placeholder="Search by test name or code…" bind:value={searchText} oninput={onSearch} />
      </div>
      <label class="sr-only" for="department">Department</label>
      <select id="department" class="select" value={department} onchange={(e) => setQuery({ department: e.currentTarget.value, page: null })}>
        <option value="">All departments</option>
        {#each departments as d (d.id)}<option value={d.id}>{d.name}{d.is_active ? "" : " (switched off)"}</option>{/each}
      </select>
      <label class="check-row">
        <input class="checkbox" type="checkbox" checked={showOff} onchange={(e) => setQuery({ all: e.currentTarget.checked ? "1" : null, page: null })} />
        <span>Show switched-off</span>
      </label>
    </div>

    {#if loadError}
      <div class="card-content"><div class="alert alert-destructive" role="alert"><Icon name="alert" /><div>{loadError} <button class="link-button" onclick={() => reload++}>Try again</button></div></div></div>
    {:else if data}
      <div class="table-wrap" aria-busy={loading}>
        <table class="table">
          <thead><tr><th>Test</th><th>Department</th><th>Type</th><th class="num">Price</th><th>Status</th>{#if canManage}<th><span class="sr-only">Actions</span></th>{/if}</tr></thead>
          <tbody>
            {#each data.items as t (t.id)}
              <tr>
                <td><div class="cell-title">{t.name}</div>{#if t.code}<div class="cell-sub mono">{t.code}</div>{/if}</td>
                <td>{t.department.name}</td>
                <td>
                  {#if t.test_type}
                    <div class="row-wrap gap-sm"><span class="badge badge-navy badge-plain">{t.test_type.name}</span>
                      {#if t.test_type.is_imaging}<span class="badge badge-info badge-plain">Imaging</span>{/if}</div>
                  {:else}<span class="text-muted">—</span>{/if}
                </td>
                <td class="num money">{rupees(t.price)}</td>
                <td>{#if t.is_active}<span class="badge badge-success">Active</span>{:else}<span class="badge badge-destructive">Switched off</span>{/if}</td>
                {#if canManage}<td class="num"><button class="btn btn-outline btn-sm" onclick={() => openEdit(t)} aria-label="Edit {t.name}"><Icon name="edit" size="sm" /> Edit</button></td>{/if}
              </tr>
            {:else}
              <tr><td colspan={canManage ? 6 : 5}><div class="empty"><Icon name="flask" />{search || department ? "No test matches these filters." : "No tests yet."}</div></td></tr>
            {/each}
          </tbody>
        </table>
      </div>
      {#if data.total > 0}<Pagination page={data.page} size={data.size} total={data.total} onchange={(p) => setQuery({ page: p }, { replace: false })} />{/if}
    {:else}
      <div class="empty" aria-busy="true">Loading…</div>
    {/if}
  {/if}
</section>

<Dialog bind:open={dialogOpen} title={editing ? `Edit ${editing.name}` : "Add a test"} icon={editing ? "edit" : "flask"} tone="info"
        description={editing ? "A new price applies to new bills. Bills already made keep the price they were billed at." : ""}>
  <form id="test-form" class="stack" onsubmit={(e) => { e.preventDefault(); save(); }} novalidate>
    <div class="grid-2">
      <Field id="t_name" label="Name" required error={errors.name}>
        {#snippet children({ invalid, describedby })}
          <input id="t_name" class="input" bind:value={form.name} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
      <Field id="t_code" label="Short code" error={errors.code} hint="Optional. Lets the front desk find the test quickly.">
        {#snippet children({ invalid, describedby })}
          <input id="t_code" class="input mono" maxlength="20" bind:value={form.code} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
    </div>
    <div class="grid-2">
      <Field id="t_dept" label="Department" required error={errors.department_id}>
        {#snippet children({ invalid, describedby })}
          <select id="t_dept" class="select" bind:value={form.department_id} aria-invalid={invalid} aria-describedby={describedby}>
            <option value="" disabled>Choose…</option>
            {#each deptOptions as d (d.id)}<option value={d.id}>{d.name}</option>{/each}
          </select>
        {/snippet}
      </Field>
      <Field id="t_type" label="Type" error={errors.test_type_id}>
        {#snippet children({ invalid, describedby })}
          <select id="t_type" class="select" bind:value={form.test_type_id} aria-invalid={invalid} aria-describedby={describedby}>
            <option value="">No type</option>
            {#each typeOptions as t (t.id)}<option value={t.id}>{t.name}{t.is_imaging ? " (has images)" : ""}</option>{/each}
          </select>
        {/snippet}
      </Field>
    </div>
    <Field id="t_price" label="Price (₹)" required error={errors.price}>
      {#snippet children({ invalid, describedby })}
        <input id="t_price" class="input money" type="number" min="0" step="0.01" inputmode="decimal" bind:value={form.price}
               aria-invalid={invalid} aria-describedby={describedby} />
      {/snippet}
    </Field>
    <label class="check-row check-top">
      <input class="checkbox" type="checkbox" bind:checked={form.is_active} />
      <span><span class="font-semibold">Active</span> <span class="text-muted">· switched-off tests can't be added to new bills.</span></span>
    </label>
  </form>
  {#snippet footer()}
    <button class="btn btn-outline" type="button" onclick={() => (dialogOpen = false)}>Cancel</button>
    <button class="btn btn-primary" type="submit" form="test-form" disabled={saving}>{saving ? "Saving…" : editing ? "Save changes" : "Add test"}</button>
  {/snippet}
</Dialog>
