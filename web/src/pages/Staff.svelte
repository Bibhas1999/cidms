<script lang="ts">
  let { embedded = false }: { embedded?: boolean; params?: Record<string, string> } = $props();
  import Dialog from "../components/Dialog.svelte";
  import Field from "../components/Field.svelte";
  import Icon from "../components/Icon.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import Pagination from "../components/Pagination.svelte";
  import { ApiError, get, patch, post } from "../lib/api";
  import { confirmDialog } from "../lib/confirm.svelte";
  import { dateTime } from "../lib/format";
  import { router, setQuery } from "../lib/router.svelte";
  import { session } from "../lib/session.svelte";
  import { notify, notifyError } from "../lib/toast.svelte";
  import type { Page, Role, Staff } from "../lib/types";

  const SIZE = $derived(Math.min(100, Number(router.query.get("size")) || 25));
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
    get<Role[]>("/api/roles").then((r) => (roles = r)).catch((e) => notifyError(e));
  });

  let searchTimer: ReturnType<typeof setTimeout>;
  function onSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => setQuery({ search: searchText.trim(), page: null }), 300);
  }

  const initials = (name: string) => name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();

  // ---------- add / edit ----------
  type Form = { full_name: string; email: string; mobile: string; role_ids: string[]; temporary_password: string; is_active: boolean };
  const blank = (): Form => ({ full_name: "", email: "", mobile: "", role_ids: [], temporary_password: "", is_active: true });

  let dialogOpen = $state(false);
  let editing = $state<Staff | null>(null);
  let form = $state<Form>(blank());
  let errors = $state<Record<string, string>>({});
  let saving = $state(false);

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
        notify(`${form.full_name} updated.`);
      } else {
        await post("/api/staff", { full_name: form.full_name, email: form.email, mobile: form.mobile, role_ids: form.role_ids,
                                   temporary_password: form.temporary_password });
        notify(`Give them this temporary password: ${form.temporary_password}. They choose their own when they first sign in.`,
               { kind: "info", title: `${form.full_name} added`, duration: 0 });
      }
      dialogOpen = false;
      reload++;
    } catch (e) {
      if (e instanceof ApiError && Object.keys(e.fieldErrors).length) errors = e.fieldErrors;
      else notifyError(e, { title: "Couldn't save" });
    } finally {
      saving = false;
    }
  }

  async function resetPassword() {
    if (!editing) return;
    const who = editing;
    if (!(await confirmDialog({ title: `Reset ${who.full_name}'s password?`, confirmLabel: "Reset password", tone: "danger",
                                message: "They'll be signed out everywhere and get a temporary password to change at their next sign-in." }))) return;
    const pw = generatePassword();
    try {
      await post(`/api/staff/${who.id}/reset-password`, { temporary_password: pw });
      notify(`Their temporary password is ${pw}. They've been signed out everywhere.`, { kind: "info", title: `Password reset for ${who.full_name}`, duration: 0 });
      dialogOpen = false;
      reload++;
    } catch (e) {
      notifyError(e, { title: "Couldn't reset the password" });
    }
  }
</script>

<PageHeader compact={embedded} eyebrow="Administration" title={session.isPlatform ? "Platform staff" : "Staff"}
            description={session.isPlatform ? "People who run the Supreme DMS platform." : "Everyone who works in the centre, and what each person can do."}>
  {#snippet actions()}<button class="btn btn-primary" onclick={openAdd}><Icon name="plus" /> Add a person</button>{/snippet}
</PageHeader>

<section class="card">
  <div class="toolbar">
    <div class="input-group">
      <Icon name="search" />
      <label class="sr-only" for="search">Search staff</label>
      <input id="search" class="input" type="search" placeholder="Search by name, email or mobile…" bind:value={searchText} oninput={onSearch} />
    </div>
    <label class="sr-only" for="active">Show</label>
    <select id="active" class="select" value={active} onchange={(e) => setQuery({ active: e.currentTarget.value, page: null })}>
      <option value="true">Active people</option>
      <option value="false">Deactivated</option>
      <option value="all">Everyone</option>
    </select>
  </div>

  {#if loadError}
    <div class="card-content"><div class="alert alert-destructive" role="alert"><Icon name="alert" /><div>{loadError} <button class="link-button" onclick={() => reload++}>Try again</button></div></div></div>
  {:else if data}
    <div class="table-wrap" aria-busy={loading}>
      <table class="table">
        <thead><tr><th>Person</th><th>Mobile</th><th>Roles</th><th>Status</th><th>Last sign-in</th><th><span class="sr-only">Actions</span></th></tr></thead>
        <tbody>
          {#each data.items as s (s.id)}
            <tr>
              <td><div class="row" style="gap:10px"><span class="avatar avatar-sm" aria-hidden="true">{initials(s.full_name)}</span>
                <div><div class="cell-title">{s.full_name}</div><div class="cell-sub">{s.email}</div></div></div></td>
              <td class="tabular">{s.mobile || "—"}</td>
              <td><div class="row-wrap" style="gap:6px">{#each s.roles as r (r.id)}<span class="badge badge-navy badge-plain">{r.name}</span>{/each}</div></td>
              <td>
                {#if !s.is_active}<span class="badge badge-destructive">Deactivated</span>
                {:else if s.must_change_password}<span class="badge badge-warning">Temporary password</span>
                {:else}<span class="badge badge-success">Active</span>{/if}
              </td>
              <td class="text-sm">{dateTime(s.last_login_at)}</td>
              <td class="num"><button class="btn btn-outline btn-sm" onclick={() => openEdit(s)} aria-label="Edit {s.full_name}"><Icon name="edit" size="sm" /> Edit</button></td>
            </tr>
          {:else}
            <tr><td colspan="6"><div class="empty"><Icon name="users" />{search ? "Nobody matches that search." : "Nobody here yet."}</div></td></tr>
          {/each}
        </tbody>
      </table>
    </div>
    {#if data.total > 0}<Pagination page={data.page} size={data.size} total={data.total} onchange={(p) => setQuery({ page: p }, { replace: false })} />{/if}
  {:else}
    <div class="empty" aria-busy="true">Loading…</div>
  {/if}
</section>

<Dialog bind:open={dialogOpen} title={editing ? `Edit ${editing.full_name}` : "Add a person"} icon={editing ? "edit" : "user"} tone="info"
        description={editing ? "" : "They get a temporary password and choose their own the first time they sign in."}>
  <form id="staff-form" class="stack" onsubmit={(e) => { e.preventDefault(); save(); }} novalidate>
    <Field id="full_name" label="Full name" required error={errors.full_name}>
      {#snippet children({ invalid, describedby })}
        <input id="full_name" class="input" bind:value={form.full_name} aria-invalid={invalid} aria-describedby={describedby} />
      {/snippet}
    </Field>
    <div class="grid-2">
      <Field id="email" label="Email" required error={errors.email} hint={editing ? "Email can't be changed." : ""}>
        {#snippet children({ invalid, describedby })}
          <input id="email" class="input" type="email" bind:value={form.email} disabled={!!editing} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
      <Field id="mobile" label="Mobile" error={errors.mobile}>
        {#snippet children({ invalid, describedby })}
          <input id="mobile" class="input" type="tel" bind:value={form.mobile} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
    </div>
    <fieldset class="field" style="border:0; padding:0; margin:0">
      <legend class="label" style="margin-bottom: 6px">Roles<span class="req" aria-hidden="true">*</span></legend>
      {#each roles as r (r.id)}
        <label class="check-row check-top">
          <input class="checkbox" type="checkbox" checked={form.role_ids.includes(r.id)} onchange={(e) => toggleRole(r.id, e.currentTarget.checked)} />
          <span><span class="font-semibold">{r.name}</span> <span class="text-muted">· {r.description}</span></span>
        </label>
      {/each}
      {#if errors.role_ids}<p class="field-error"><Icon name="alert" size="sm" />{errors.role_ids}</p>{/if}
    </fieldset>
    {#if !editing}
      <Field id="temp" label="Temporary password" required error={errors.temporary_password}>
        {#snippet children({ invalid, describedby })}
          <div class="row">
            <input id="temp" class="input mono" bind:value={form.temporary_password} aria-invalid={invalid} aria-describedby={describedby} />
            <button type="button" class="btn btn-outline" onclick={() => (form.temporary_password = generatePassword())}><Icon name="refresh" size="sm" /> New</button>
          </div>
        {/snippet}
      </Field>
    {:else}
      <label class="check-row check-top">
        <input class="checkbox" type="checkbox" bind:checked={form.is_active} disabled={editing.id === session.me?.id} />
        <span><span class="font-semibold">Active</span> <span class="text-muted">· deactivating signs them out everywhere; their history stays.</span></span>
      </label>
      {#if errors.is_active}<p class="field-error"><Icon name="alert" size="sm" />{errors.is_active}</p>{/if}
    {/if}
  </form>
  {#snippet footer()}
    {#if editing}<button class="btn btn-ghost-destructive" style="margin-right:auto" type="button" onclick={resetPassword}><Icon name="lock" size="sm" /> Reset password</button>{/if}
    <button class="btn btn-outline" type="button" onclick={() => (dialogOpen = false)}>Cancel</button>
    <button class="btn btn-primary" type="submit" form="staff-form" disabled={saving}>{saving ? "Saving…" : editing ? "Save changes" : "Add person"}</button>
  {/snippet}
</Dialog>
