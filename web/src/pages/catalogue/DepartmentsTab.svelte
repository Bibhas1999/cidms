<script lang="ts">
  import Dialog from "../../components/Dialog.svelte";
  import Field from "../../components/Field.svelte";
  import Button from "../../components/Button.svelte";
  import DataTable from "../../components/DataTable.svelte";
  import StatusBadge from "../../components/StatusBadge.svelte";
  import Toolbar from "../../components/Toolbar.svelte";
  import type { RowAction } from "../../components/RowMenu.svelte";
  import { ApiError, post, put } from "../../lib/api";
  import { session } from "../../lib/session.svelte";
  import { notify, notifyError } from "../../lib/toast.svelte";
  import type { Department } from "../../lib/types";

  // The Departments tab of Tests & prices. The list is loaded by the page (the tests tab needs it too).
  let { departments, loaded, onchanged }: { departments: Department[]; loaded: boolean; onchanged: () => void } = $props();
  const canManage = $derived(session.can("catalogue.manage"));

  let dialogOpen = $state(false);
  let editing = $state<Department | null>(null);
  let form = $state({ name: "", is_active: true });
  let errors = $state<Record<string, string>>({});
  let saving = $state(false);

  function openAdd() {
    editing = null;
    form = { name: "", is_active: true };
    errors = {};
    dialogOpen = true;
  }

  function openEdit(d: Department) {
    editing = d;
    form = { name: d.name, is_active: d.is_active };
    errors = {};
    dialogOpen = true;
  }

  async function save() {
    saving = true;
    errors = {};
    try {
      if (editing) await put(`/api/departments/${editing.id}`, form);
      else await post("/api/departments", form);
      notify(editing ? `${form.name} saved.` : `${form.name} added.`);
      dialogOpen = false;
      onchanged();
    } catch (e) {
      if (e instanceof ApiError && Object.keys(e.fieldErrors).length) errors = e.fieldErrors;
      else notifyError(e, { title: "Couldn't save" });
    } finally {
      saving = false;
    }
  }

  async function setActive(d: Department, on: boolean) {
    try {
      await put(`/api/departments/${d.id}`, { name: d.name, is_active: on });
      notify(on ? `${d.name} switched on.` : `${d.name} switched off.`);
      onchanged();
    } catch (e) {
      notifyError(e, { title: "Couldn't change it" });
    }
  }

  function actionsFor(d: Department): RowAction[] {
    return [
      { label: "Rename", icon: "edit", onclick: () => openEdit(d) },
      d.is_active ? { label: "Switch off", icon: "lock", tone: "danger", onclick: () => setActive(d, false), hint: "Can't be chosen for new tests; existing tests keep it" }
                  : { label: "Switch on", icon: "check", onclick: () => setActive(d, true) },
      { label: "Its tests", icon: "flask", href: `/tests?department=${d.id}` },
    ];
  }
</script>

{#snippet statusCell(d: Department)}<StatusBadge active={d.is_active} help={d.is_active ? "" : "Can't be chosen for new tests."} />{/snippet}

{#if canManage}
  <Toolbar>
    <p class="text-sm text-muted">Departments group the tests: Pathology, Radiology, Cardiology…</p>
    {#snippet end()}<Button variant="primary" size="sm" icon="plus" onclick={openAdd}>Add a department</Button>{/snippet}
  </Toolbar>
{/if}
<DataTable label="Departments" rows={departments} loading={!loaded} actions={canManage ? actionsFor : undefined}
           actionsLabel={(d) => `Actions for ${d.name}`} onrowclick={canManage ? openEdit : undefined}
           empty={{ icon: "layers", title: "No departments yet." }}
           columns={[
             { key: "name", label: "Department", value: (d) => d.name, class: "cell-title", mobile: "title" },
             { key: "status", label: "Status", cell: statusCell, mobile: "end" },
           ]} />

<Dialog bind:open={dialogOpen} title={editing ? `Edit ${editing.name}` : "Add a department"} icon={editing ? "edit" : "layers"} tone="info">
  <form id="department-form" class="stack" onsubmit={(e) => { e.preventDefault(); save(); }} novalidate>
    <Field id="dept_name" label="Name" required error={errors.name} tip="A section of the centre, e.g. Pathology or Radiology. Tests, bills and reports can be grouped and filtered by it.">
      {#snippet children({ invalid, describedby })}
        <input id="dept_name" class="input" bind:value={form.name} aria-invalid={invalid} aria-describedby={describedby} />
      {/snippet}
    </Field>
    <label class="check-row check-top">
      <input class="checkbox" type="checkbox" bind:checked={form.is_active} />
      <span><span class="font-semibold">Active</span> <span class="text-muted">· switched-off departments can't be chosen for new tests.</span></span>
    </label>
  </form>
  {#snippet footer()}
    <Button onclick={() => (dialogOpen = false)}>Cancel</Button>
    <Button variant="primary" type="submit" form="department-form" loading={saving} loadingText="Saving…">{editing ? "Save changes" : "Add department"}</Button>
  {/snippet}
</Dialog>
