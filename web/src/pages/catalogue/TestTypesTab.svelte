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
  import type { TestType } from "../../lib/types";

  // The Test types tab of Tests & prices. The list is loaded by the page (the tests tab needs it too).
  let { types, loaded, onchanged }: { types: TestType[]; loaded: boolean; onchanged: () => void } = $props();
  const canManage = $derived(session.can("catalogue.manage"));

  let dialogOpen = $state(false);
  let editing = $state<TestType | null>(null);
  let form = $state({ name: "", is_imaging: false, is_active: true });
  let errors = $state<Record<string, string>>({});
  let saving = $state(false);

  function openAdd() {
    editing = null;
    form = { name: "", is_imaging: false, is_active: true };
    errors = {};
    dialogOpen = true;
  }

  function openEdit(t: TestType) {
    editing = t;
    form = { name: t.name, is_imaging: t.is_imaging, is_active: t.is_active };
    errors = {};
    dialogOpen = true;
  }

  async function save() {
    saving = true;
    errors = {};
    try {
      if (editing) await put(`/api/test-types/${editing.id}`, form);
      else await post("/api/test-types", form);
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

  async function setActive(t: TestType, on: boolean) {
    try {
      await put(`/api/test-types/${t.id}`, { name: t.name, is_imaging: t.is_imaging, is_active: on });
      notify(on ? `${t.name} switched on.` : `${t.name} switched off.`);
      onchanged();
    } catch (e) {
      notifyError(e, { title: "Couldn't change it" });
    }
  }

  function actionsFor(t: TestType): RowAction[] {
    return [
      { label: "Edit", icon: "edit", onclick: () => openEdit(t) },
      t.is_active ? { label: "Switch off", icon: "lock", tone: "danger", onclick: () => setActive(t, false), hint: "Can't be chosen for new tests" }
                  : { label: "Switch on", icon: "check", onclick: () => setActive(t, true) },
    ];
  }
</script>

{#snippet imgCell(t: TestType)}{#if t.is_imaging}<StatusBadge tone="info" label="Has images" help="Tests of this type are marked scanned on the worklist before they're handed over." />{:else}<span class="text-muted">—</span>{/if}{/snippet}
{#snippet statusCell(t: TestType)}<StatusBadge active={t.is_active} help={t.is_active ? "" : "Can't be chosen for new tests."} />{/snippet}

{#if canManage}
  <Toolbar>
    <p class="text-sm text-muted">Types such as X-ray, Blood test or ECG. Types with images go through scanning.</p>
    {#snippet end()}<Button variant="primary" size="sm" icon="plus" onclick={openAdd}>Add a test type</Button>{/snippet}
  </Toolbar>
{/if}
<DataTable label="Test types" rows={types} loading={!loaded} actions={canManage ? actionsFor : undefined}
           actionsLabel={(t) => `Actions for ${t.name}`} onrowclick={canManage ? openEdit : undefined}
           empty={{ icon: "tag", title: "No test types yet." }}
           columns={[
             { key: "name", label: "Test type", value: (t) => t.name, class: "cell-title", mobile: "title" },
             { key: "img", label: "Images", cell: imgCell, tip: "Imaging types (X-ray, CT, MRI, USG) are scanned before the report is handed over." },
             { key: "status", label: "Status", cell: statusCell, mobile: "end" },
           ]} />

<Dialog bind:open={dialogOpen} title={editing ? `Edit ${editing.name}` : "Add a test type"} icon={editing ? "edit" : "tag"} tone="info"
        description="Types group tests, such as X-ray, Blood test or ECG. Types with images go through scanning on the worklist.">
  <form id="type-form" class="stack" onsubmit={(e) => { e.preventDefault(); save(); }} novalidate>
    <Field id="type_name" label="Name" required error={errors.name} tip="What kind of test, e.g. X-ray, Blood test or ECG. Tick Has images for scans, so they go through scanning on the worklist.">
      {#snippet children({ invalid, describedby })}
        <input id="type_name" class="input" bind:value={form.name} aria-invalid={invalid} aria-describedby={describedby} />
      {/snippet}
    </Field>
    <label class="check-row check-top">
      <input class="checkbox" type="checkbox" bind:checked={form.is_imaging} />
      <span><span class="font-semibold">Has images (X-ray, CT, MRI, USG)</span> <span class="text-muted">· tests of this type are marked scanned before they're handed over.</span></span>
    </label>
    <label class="check-row check-top">
      <input class="checkbox" type="checkbox" bind:checked={form.is_active} />
      <span><span class="font-semibold">Active</span> <span class="text-muted">· switched-off types can't be chosen for new tests.</span></span>
    </label>
  </form>
  {#snippet footer()}
    <Button onclick={() => (dialogOpen = false)}>Cancel</Button>
    <Button variant="primary" type="submit" form="type-form" loading={saving} loadingText="Saving…">{editing ? "Save changes" : "Add test type"}</Button>
  {/snippet}
</Dialog>
