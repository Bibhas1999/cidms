<script lang="ts">
  import Dialog from "../../components/Dialog.svelte";
  import Field from "../../components/Field.svelte";
  import Icon from "../../components/Icon.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import Pagination from "../../components/Pagination.svelte";
  import { ApiError, get, post, put } from "../../lib/api";
  import { router, setQuery } from "../../lib/router.svelte";
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
  let searchText = $state(router.query.get("search") ?? "");

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

  let searchTimer: ReturnType<typeof setTimeout>;
  function onSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => setQuery({ search: searchText.trim(), page: null }), 300);
  }

  // ---------- add / edit ----------
  type Form = { name: string; qualification: string; phone: string; is_active: boolean };
  const blank = (): Form => ({ name: "", qualification: "", phone: "", is_active: true });

  let dialogOpen = $state(false);
  let editing = $state<Doctor | null>(null);
  let form = $state<Form>(blank());
  let errors = $state<Record<string, string>>({});
  let saving = $state(false);

  function openAdd() {
    editing = null;
    form = blank();
    errors = {};
    dialogOpen = true;
  }

  function openEdit(d: Doctor) {
    editing = d;
    form = { name: d.name, qualification: d.qualification, phone: d.phone, is_active: d.is_active };
    errors = {};
    dialogOpen = true;
  }

  async function save() {
    saving = true;
    errors = {};
    try {
      if (editing) await put(`/api/doctors/${editing.id}`, form);
      else await post("/api/doctors", form);
      notify(editing ? `${form.name} saved.` : `${form.name} added.`);
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

<PageHeader eyebrow="Catalogue" title="Referring doctors"
            description="Doctors who send patients to the centre. A doctor is added automatically when a new name is typed on a bill.">
  {#snippet actions()}
    {#if canManage}<button class="btn btn-primary" onclick={openAdd}><Icon name="plus" /> Add a doctor</button>{/if}
  {/snippet}
</PageHeader>

<section class="card">
  <div class="toolbar">
    <div class="input-group">
      <Icon name="search" />
      <label class="sr-only" for="search">Search doctors</label>
      <input id="search" class="input" type="search" placeholder="Search by name…" bind:value={searchText} oninput={onSearch} />
    </div>
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
        <thead><tr><th>Doctor</th><th>Qualification</th><th>Phone</th><th>Status</th>{#if canManage}<th><span class="sr-only">Actions</span></th>{/if}</tr></thead>
        <tbody>
          {#each data.items as d (d.id)}
            <tr>
              <td class="cell-title">{d.name}</td>
              <td>{d.qualification || "—"}</td>
              <td class="tabular">{d.phone || "—"}</td>
              <td>{#if d.is_active}<span class="badge badge-success">Active</span>{:else}<span class="badge badge-destructive">Switched off</span>{/if}</td>
              {#if canManage}<td class="num"><button class="btn btn-outline btn-sm" onclick={() => openEdit(d)} aria-label="Edit {d.name}"><Icon name="edit" size="sm" /> Edit</button></td>{/if}
            </tr>
          {:else}
            <tr><td colspan={canManage ? 5 : 4}><div class="empty"><Icon name="stethoscope" />{search ? "No doctor matches that search." : "No referring doctors yet."}</div></td></tr>
          {/each}
        </tbody>
      </table>
    </div>
    {#if data.total > 0}<Pagination page={data.page} size={data.size} total={data.total} onchange={(p) => setQuery({ page: p }, { replace: false })} />{/if}
  {:else}
    <div class="empty" aria-busy="true">Loading…</div>
  {/if}
</section>

<Dialog bind:open={dialogOpen} title={editing ? `Edit ${editing.name}` : "Add a doctor"} icon={editing ? "edit" : "stethoscope"} tone="info">
  <form id="doctor-form" class="stack" onsubmit={(e) => { e.preventDefault(); save(); }} novalidate>
    <Field id="d_name" label="Name" required error={errors.name}>
      {#snippet children({ invalid, describedby })}
        <input id="d_name" class="input" bind:value={form.name} aria-invalid={invalid} aria-describedby={describedby} />
      {/snippet}
    </Field>
    <div class="grid-2">
      <Field id="d_qual" label="Qualification" error={errors.qualification} hint="For example MBBS, MD.">
        {#snippet children({ invalid, describedby })}
          <input id="d_qual" class="input" bind:value={form.qualification} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
      <Field id="d_phone" label="Phone" error={errors.phone}>
        {#snippet children({ invalid, describedby })}
          <input id="d_phone" class="input" type="tel" inputmode="tel" bind:value={form.phone} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
    </div>
    <label class="check-row check-top">
      <input class="checkbox" type="checkbox" bind:checked={form.is_active} />
      <span><span class="font-semibold">Active</span> <span class="text-muted">· switched-off doctors aren't suggested on new bills.</span></span>
    </label>
  </form>
  {#snippet footer()}
    <button class="btn btn-outline" type="button" onclick={() => (dialogOpen = false)}>Cancel</button>
    <button class="btn btn-primary" type="submit" form="doctor-form" disabled={saving}>{saving ? "Saving…" : editing ? "Save changes" : "Add doctor"}</button>
  {/snippet}
</Dialog>
