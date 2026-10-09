<script lang="ts">
  import Dialog from "../components/Dialog.svelte";
  import Field from "../components/Field.svelte";
  import Pagination from "../components/Pagination.svelte";
  import { ApiError, get, patch, post } from "../lib/api";
  import { dateTime } from "../lib/format";
  import { router, setQuery } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";
  import { toastError, toasts } from "../lib/toast.svelte";
  import type { Page, Role, Staff } from "../lib/types";

  const SIZE = 25;
  const page = $derived(Number(router.query.get("page") ?? 1) || 1);
  const search = $derived(router.query.get("search") ?? "");
  const active = $derived(router.query.get("active") ?? "true");

  let data = $state<Page<Staff> | null>(null);
  let loadError = $state("");
  let loading = $state(false);
  let reload = $state(0);
  let roles = $state<Role[]>([]);
  let searchText = $state(router.query.get("search") ?? "");

  $effect(() => {
    const ctrl = new AbortController();
    const query = { page, size: SIZE, search, active: active === "all" ? undefined : active };
    reload;
    loading = true;
    get<Page<Staff>>("/api/staff", query, ctrl.signal)
      .then((d) => { data = d; loadError = ""; })
      .catch((e) => { if (e.name !== "AbortError") loadError = e.message; })
      .finally(() => { loading = false; });
    return () => ctrl.abort();
  });

  $effect(() => {
    get<Role[]>("/api/roles").then((r) => (roles = r)).catch(toastError);
  });

  let searchTimer: ReturnType<typeof setTimeout>;
  function onSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => setQuery({ search: searchText.trim(), page: null }), 300);
  }

  // ---------- add / edit ----------
  type Form = { full_name: string; email: string; mobile: string; role_ids: string[]; temporary_password: string; is_active: boolean };
  const blank = (): Form => ({ full_name: "", email: "", mobile: "", role_ids: [], temporary_password: "", is_active: true });

  let dialogOpen = $state(false);
  let editing = $state<Staff | null>(null);
  let form = $state<Form>(blank());
  let errors = $state<Record<string, string>>({});
  let saving = $state(false);
  let resetPassword = $state("");

  function generatePassword(): string {
    const words = "Lotus Mango River Cedar Pearl Tiger Coral Amber Maple Falcon".split(" ");
    const pick = () => words[crypto.getRandomValues(new Uint32Array(1))[0] % words.length];
    return `${pick()}-${pick()}-${(crypto.getRandomValues(new Uint32Array(1))[0] % 900) + 100}`;
  }

  function openAdd() {
    editing = null;
    form = { ...blank(), temporary_password: generatePassword() };
    errors = {};
    dialogOpen = true;
  }

  function openEdit(s: Staff) {
    editing = s;
    form = { full_name: s.full_name, email: s.email, mobile: s.mobile, role_ids: s.roles.map((r) => r.id), temporary_password: "", is_active: s.is_active };
    errors = {};
    resetPassword = "";
    dialogOpen = true;
  }

  function toggleRole(id: string, on: boolean) {
    form.role_ids = on ? [...form.role_ids, id] : form.role_ids.filter((r) => r !== id);
  }

  async function save() {
    saving = true;
    errors = {};
    try {
      if (editing) {
        await patch(`/api/staff/${editing.id}`, { full_name: form.full_name, mobile: form.mobile, role_ids: form.role_ids, is_active: form.is_active });
        toasts.show(`${form.full_name} updated.`);
      } else {
        await post("/api/staff", { full_name: form.full_name, email: form.email, mobile: form.mobile, role_ids: form.role_ids,
                                   temporary_password: form.temporary_password });
        toasts.show(`${form.full_name} added. Give them their temporary password: ${form.temporary_password}`, "success");
      }
      dialogOpen = false;
      reload++;
    } catch (e) {
      if (e instanceof ApiError && Object.keys(e.fieldErrors).length) errors = e.fieldErrors;
      else toastError(e);
    } finally {
      saving = false;
    }
  }

  async function doReset() {
    if (!editing) return;
    const pw = resetPassword || generatePassword();
    try {
      await post(`/api/staff/${editing.id}/reset-password`, { temporary_password: pw });
      toasts.show(`Password reset. ${editing.full_name}'s temporary password is ${pw}. They've been signed out everywhere.`, "info");
      resetPassword = "";
      dialogOpen = false;
      reload++;
    } catch (e) {
      if (e instanceof ApiError && e.field) errors = { reset: e.message };
      else toastError(e);
    }
  }
</script>

<div class="stack">
  <div class="toolbar">
    <h1 class="grow">{session.isPlatform ? "Platform staff" : "Staff"}</h1>
    <button class="btn primary" onclick={openAdd}>Add a person</button>
  </div>

  <div class="card">
    <div class="toolbar filters">
      <label class="sr-only" for="search">Search staff</label>
      <input id="search" type="search" placeholder="Search by name, email or mobile" bind:value={searchText} oninput={onSearch} />
      <label class="sr-only" for="active">Show</label>
      <select id="active" value={active} onchange={(e) => setQuery({ active: e.currentTarget.value, page: null })}>
        <option value="true">Active</option>
        <option value="false">Deactivated</option>
        <option value="all">Everyone</option>
      </select>
    </div>

    {#if loadError}
      <div class="alert" role="alert">{loadError} <button class="btn link" onclick={() => reload++}>Try again</button></div>
    {:else if data}
      <div class="table-wrap" aria-busy={loading}>
        <table class="data">
          <thead><tr><th>Name</th><th>Mobile</th><th>Roles</th><th>Status</th><th>Last sign-in</th><th><span class="sr-only">Actions</span></th></tr></thead>
          <tbody>
            {#each data.items as s (s.id)}
              <tr>
                <td><strong>{s.full_name}</strong><div class="muted">{s.email}</div></td>
                <td>{s.mobile || "—"}</td>
                <td>{s.roles.map((r) => r.name).join(", ")}</td>
                <td>
                  {#if !s.is_active}<span class="badge bad">Deactivated</span>
                  {:else if s.must_change_password}<span class="badge warn">Temporary password</span>
                  {:else}<span class="badge good">Active</span>{/if}
                </td>
                <td>{dateTime(s.last_login_at)}</td>
                <td><button class="btn small" onclick={() => openEdit(s)} aria-label="Edit {s.full_name}">Edit</button></td>
              </tr>
            {:else}
              <tr><td colspan="6" class="muted empty">{search ? "Nobody matches that search." : "Nobody here yet."}</td></tr>
            {/each}
          </tbody>
        </table>
      </div>
      <Pagination page={data.page} size={data.size} total={data.total} onchange={(p) => setQuery({ page: p }, { replace: false })} />
    {:else}
      <p class="muted empty">Loading…</p>
    {/if}
  </div>
</div>

<Dialog bind:open={dialogOpen} title={editing ? `Edit ${editing.full_name}` : "Add a person"}>
  <form id="staff-form" class="stack" onsubmit={(e) => { e.preventDefault(); save(); }} novalidate>
    <Field id="full_name" label="Full name" required error={errors.full_name}>
      {#snippet children({ invalid, describedby })}
        <input id="full_name" bind:value={form.full_name} aria-invalid={invalid} aria-describedby={describedby} />
      {/snippet}
    </Field>
    <div class="row-2">
      <Field id="email" label="Email" required error={errors.email} hint={editing ? "Email can't be changed." : ""}>
        {#snippet children({ invalid, describedby })}
          <input id="email" type="email" bind:value={form.email} disabled={!!editing} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
      <Field id="mobile" label="Mobile" error={errors.mobile}>
        {#snippet children({ invalid, describedby })}
          <input id="mobile" type="tel" bind:value={form.mobile} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
    </div>
    <fieldset>
      <legend>Roles <span class="req" aria-hidden="true">*</span></legend>
      {#each roles as r (r.id)}
        <label class="check">
          <input type="checkbox" checked={form.role_ids.includes(r.id)} onchange={(e) => toggleRole(r.id, e.currentTarget.checked)} />
          <span><strong>{r.name}</strong> <span class="muted">— {r.description}</span></span>
        </label>
      {/each}
      {#if errors.role_ids}<div class="err">{errors.role_ids}</div>{/if}
    </fieldset>
    {#if !editing}
      <Field id="temp" label="Temporary password" required error={errors.temporary_password}
             hint="They'll be asked to choose their own the first time they sign in.">
        {#snippet children({ invalid, describedby })}
          <div class="toolbar">
            <input id="temp" class="grow mono" bind:value={form.temporary_password} aria-invalid={invalid} aria-describedby={describedby} />
            <button type="button" class="btn small" onclick={() => (form.temporary_password = generatePassword())}>New</button>
          </div>
        {/snippet}
      </Field>
    {:else}
      <label class="check">
        <input type="checkbox" bind:checked={form.is_active} disabled={editing.id === session.me?.id} />
        <span>Active <span class="muted">— deactivating signs them out everywhere; their history stays.</span></span>
      </label>
      {#if errors.is_active}<div class="err">{errors.is_active}</div>{/if}
      <details>
        <summary>Reset their password</summary>
        <div class="toolbar reset">
          <input class="grow mono" placeholder="Leave blank to generate one" bind:value={resetPassword} aria-label="New temporary password" />
          <button type="button" class="btn danger" onclick={doReset}>Reset password</button>
        </div>
        {#if errors.reset}<div class="err">{errors.reset}</div>{/if}
      </details>
    {/if}
  </form>
  {#snippet footer()}
    <button class="btn" onclick={() => (dialogOpen = false)}>Cancel</button>
    <button class="btn primary" type="submit" form="staff-form" disabled={saving}>{saving ? "Saving…" : editing ? "Save changes" : "Add person"}</button>
  {/snippet}
</Dialog>

<style>
  .filters { padding: 12px; border-bottom: 1px solid var(--border); }
  .filters input { max-width: 360px; }
  .filters select { width: auto; }
  .table-wrap { overflow-x: auto; }
  .table-wrap[aria-busy="true"] { opacity: .6; }
  .empty { padding: 24px; text-align: center; }
  fieldset { border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 14px; display: grid; gap: 8px; margin: 0; }
  legend { font-weight: 550; font-size: 13px; padding: 0 4px; }
  .req, .err { color: var(--danger); }
  .err { font-size: 12px; }
  .check { display: flex; gap: 8px; align-items: flex-start; }
  .check input { margin-top: 3px; }
  details summary { cursor: pointer; color: var(--brand); font-weight: 550; }
  .reset { margin-top: 10px; }
</style>
