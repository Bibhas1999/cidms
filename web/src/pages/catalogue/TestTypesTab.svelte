<script lang="ts">
  import Dialog from "../../components/Dialog.svelte";
  import Field from "../../components/Field.svelte";
  import Icon from "../../components/Icon.svelte";
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
</script>

{#if canManage}
  <div class="toolbar justify-end"><button class="btn btn-primary btn-sm" onclick={openAdd}><Icon name="plus" size="sm" /> Add a test type</button></div>
{/if}
{#if !loaded}
  <div class="empty" aria-busy="true">Loading…</div>
{:else}
  <div class="table-wrap">
    <table class="table">
      <thead><tr><th>Test type</th><th>Images</th><th>Status</th>{#if canManage}<th><span class="sr-only">Actions</span></th>{/if}</tr></thead>
      <tbody>
        {#each types as t (t.id)}
          <tr>
            <td class="cell-title">{t.name}</td>
            <td>{#if t.is_imaging}<span class="badge badge-info badge-plain">Has images</span>{:else}<span class="text-muted">—</span>{/if}</td>
            <td>{#if t.is_active}<span class="badge badge-success">Active</span>{:else}<span class="badge badge-destructive">Switched off</span>{/if}</td>
            {#if canManage}<td class="num"><button class="btn btn-outline btn-sm" onclick={() => openEdit(t)} aria-label="Edit {t.name}"><Icon name="edit" size="sm" /> Edit</button></td>{/if}
          </tr>
        {:else}
          <tr><td colspan={canManage ? 4 : 3}><div class="empty"><Icon name="tag" />No test types yet.</div></td></tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}

<Dialog bind:open={dialogOpen} title={editing ? `Edit ${editing.name}` : "Add a test type"} icon={editing ? "edit" : "tag"} tone="info"
        description="Types group tests, such as X-ray, Blood test or ECG. Types with images go through scanning on the worklist.">
  <form id="type-form" class="stack" onsubmit={(e) => { e.preventDefault(); save(); }} novalidate>
    <Field id="type_name" label="Name" required error={errors.name}>
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
    <button class="btn btn-outline" type="button" onclick={() => (dialogOpen = false)}>Cancel</button>
    <button class="btn btn-primary" type="submit" form="type-form" disabled={saving}>{saving ? "Saving…" : editing ? "Save changes" : "Add test type"}</button>
  {/snippet}
</Dialog>
