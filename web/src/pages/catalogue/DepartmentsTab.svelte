<script lang="ts">
  import Dialog from "../../components/Dialog.svelte";
  import Field from "../../components/Field.svelte";
  import Icon from "../../components/Icon.svelte";
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
</script>

{#if canManage}
  <div class="toolbar justify-end"><button class="btn btn-primary btn-sm" onclick={openAdd}><Icon name="plus" size="sm" /> Add a department</button></div>
{/if}
{#if !loaded}
  <div class="empty" aria-busy="true">Loading…</div>
{:else}
  <div class="table-wrap">
    <table class="table">
      <thead><tr><th>Department</th><th>Status</th>{#if canManage}<th><span class="sr-only">Actions</span></th>{/if}</tr></thead>
      <tbody>
        {#each departments as d (d.id)}
          <tr>
            <td class="cell-title">{d.name}</td>
            <td>{#if d.is_active}<span class="badge badge-success">Active</span>{:else}<span class="badge badge-destructive">Switched off</span>{/if}</td>
            {#if canManage}<td class="num"><button class="btn btn-outline btn-sm" onclick={() => openEdit(d)} aria-label="Edit {d.name}"><Icon name="edit" size="sm" /> Edit</button></td>{/if}
          </tr>
        {:else}
          <tr><td colspan={canManage ? 3 : 2}><div class="empty"><Icon name="layers" />No departments yet.</div></td></tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}

<Dialog bind:open={dialogOpen} title={editing ? `Edit ${editing.name}` : "Add a department"} icon={editing ? "edit" : "layers"} tone="info">
  <form id="department-form" class="stack" onsubmit={(e) => { e.preventDefault(); save(); }} novalidate>
    <Field id="dept_name" label="Name" required error={errors.name}>
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
    <button class="btn btn-outline" type="button" onclick={() => (dialogOpen = false)}>Cancel</button>
    <button class="btn btn-primary" type="submit" form="department-form" disabled={saving}>{saving ? "Saving…" : editing ? "Save changes" : "Add department"}</button>
  {/snippet}
</Dialog>
