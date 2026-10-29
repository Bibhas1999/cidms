<script lang="ts">
  let { embedded = false }: { embedded?: boolean; params?: Record<string, string> } = $props();
  import { z } from "zod";
  import Button from "../components/Button.svelte";
  import DataTable from "../components/DataTable.svelte";
  import Dialog from "../components/Dialog.svelte";
  import Field from "../components/Field.svelte";
  import FilterBar from "../components/FilterBar.svelte";
  import FormErrors from "../components/FormErrors.svelte";
  import Icon from "../components/Icon.svelte";
  import IconButton from "../components/IconButton.svelte";
  import InfoTip from "../components/InfoTip.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import PhoneInput from "../components/PhoneInput.svelte";
  import StatusBadge from "../components/StatusBadge.svelte";
  import type { RowAction } from "../components/RowMenu.svelte";
  import { get, patch, post } from "../lib/api";
  import { confirmDialog } from "../lib/confirm.svelte";
  import { Form } from "../lib/form.svelte";
  import { dateTime } from "../lib/format";
  import { formatPhone } from "../lib/phone";
  import { router, setQuery } from "../lib/router.svelte";
  import { email, phone, submitting, text } from "../lib/schemas";
  import { session } from "../lib/session.svelte";
  import { notify, notifyError } from "../lib/toast.svelte";
  import { tooltip } from "../lib/tooltip";
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

  const initials = (name: string) => name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();

  // ---------- add / edit ----------
  let dialogOpen = $state(false);
  let editing = $state<Staff | null>(null);
  let shownPassword = $state<{ password: string; name: string; reset: boolean } | null>(null);
  let pwCopied = $state(false);

  async function copyPassword() {
    try {
      await navigator.clipboard.writeText(shownPassword!.password);
      pwCopied = true;
      notify("Password copied.");
    } catch {
      notify("Couldn't copy. Select the text and copy it yourself.", { kind: "warning" });
    }
  }

  const schema = z.object({
    full_name: text("Enter their full name.", 200, 2),
    email: z.string(),
    mobile: phone(false),
    role_ids: z.array(z.string()).min(1, "Choose at least one role."),
    temporary_password: z.string(),
    is_active: z.boolean(),
  });
  const labels = { full_name: "Full name", email: "Email", mobile: "Mobile", role_ids: "Roles", temporary_password: "Temporary password", is_active: "Active" };
  const blank = { full_name: "", email: "", mobile: "", role_ids: [] as string[], temporary_password: "", is_active: true };

  const form = new Form({
    schema, initial: blank,
    rules: (v, add) => {
      if (editing) return;
      const e = email().safeParse(v.email);
      if (!e.success) add("email", e.error.issues[0].message);
      if (v.temporary_password.trim() && v.temporary_password.trim().length < 10) add("temporary_password", "Use at least 10 characters, or leave it empty for a random one.");
    },
    onSubmit: async (v) => {
      if (editing) {
        await patch(`/api/staff/${editing.id}`, { full_name: v.full_name, mobile: v.mobile, role_ids: v.role_ids, is_active: v.is_active });
        notify(`${v.full_name} updated.`);
      } else {
        const made = await post<{ temporary_password: string }>("/api/staff", { full_name: v.full_name, email: v.email.trim(), mobile: v.mobile,
                                                                                role_ids: v.role_ids, temporary_password: v.temporary_password });
        pwCopied = false;
        shownPassword = { password: made.temporary_password, name: v.full_name, reset: false };
      }
      dialogOpen = false;
      reload++;
    },
  });

  // A random one-time password for each person (like "Kmrt-4829-Vbxe"). It works once: at the first sign-in
  // they must choose their own. Left empty, the server makes one; either way it's shown once after saving.
  const LETTERS = "abcdefghjkmnpqrstuvwxyz";
  const pick = (chars: string, n: number) => Array.from(crypto.getRandomValues(new Uint32Array(n)), (x) => chars[x % chars.length]).join("");
  const word = () => { const w = pick(LETTERS, 4); return w[0].toUpperCase() + w.slice(1); };
  const generatePassword = (): string => `${word()}-${pick("23456789", 4)}-${word()}`;

  function openAdd() {
    editing = null;
    form.reset({ ...blank, temporary_password: generatePassword() });
    dialogOpen = true;
  }

  function openEdit(s: Staff) {
    editing = s;
    form.reset({ full_name: s.full_name, email: s.email, mobile: s.mobile, role_ids: s.roles.map((r) => r.id), temporary_password: "", is_active: s.is_active });
    dialogOpen = true;
  }

  function toggleRole(id: string, on: boolean) {
    form.values.role_ids = on ? [...form.values.role_ids, id] : form.values.role_ids.filter((r) => r !== id);
    form.touched.role_ids = true;
    form.validate();
  }

  async function resetPassword(who: Staff) {
    if (!(await confirmDialog({ title: `Reset ${who.full_name}'s password?`, confirmLabel: "Reset password", tone: "danger",
                                message: "They'll be signed out everywhere and get a temporary password to change at their next sign-in." }))) return;
    try {
      const { temporary_password: pw } = await post<{ temporary_password: string }>(`/api/staff/${who.id}/reset-password`, {});
      pwCopied = false;
      shownPassword = { password: pw, name: who.full_name, reset: true };
      dialogOpen = false;
      reload++;
    } catch (e) {
      notifyError(e, { title: "Couldn't reset the password" });
    }
  }

  async function setActive(s: Staff, on: boolean) {
    if (!on && !(await confirmDialog({ title: `Deactivate ${s.full_name}?`, confirmLabel: "Deactivate", tone: "danger",
                                       message: "They're signed out everywhere and can't sign in. Everything they did stays in the records." }))) return;
    try {
      await patch(`/api/staff/${s.id}`, { is_active: on });
      notify(on ? `${s.full_name} can sign in again.` : `${s.full_name} deactivated.`);
      reload++;
    } catch (e) {
      notifyError(e, { title: "Couldn't change it" });
    }
  }

  function actionsFor(s: Staff): RowAction[] {
    const self = s.id === session.me?.id;
    return [
      { label: "Edit", icon: "edit", onclick: () => openEdit(s), hint: "Name, mobile and roles" },
      { label: "Reset password", icon: "lock", onclick: () => resetPassword(s), hint: "Signs them out and gives a temporary password" },
      s.is_active
        ? { label: "Deactivate", icon: "x", tone: "danger", onclick: () => setActive(s, false), disabled: self, hint: self ? "You can't deactivate yourself" : "" }
        : { label: "Reactivate", icon: "check", onclick: () => setActive(s, true) },
    ];
  }

  const ROLE_TIP = "What each person can see and do. Pick every role that applies; someone with two roles can do both jobs. The Owner can do everything.";
</script>

{#snippet personCell(s: Staff)}
  <div class="row person"><span class="avatar avatar-sm" aria-hidden="true">{initials(s.full_name)}</span>
    <div class="grow"><div class="cell-title">{s.full_name}</div><div class="cell-sub truncate">{s.email}</div></div></div>
{/snippet}
{#snippet rolesCell(s: Staff)}
  <div class="row-wrap roles">{#each s.roles as r (r.id)}<span class="badge badge-navy badge-plain" use:tooltip={r.description}>{r.name}</span>{/each}</div>
{/snippet}
{#snippet statusCell(s: Staff)}
  {#if !s.is_active}<StatusBadge tone="destructive" label="Deactivated" help="Can't sign in. Their history stays." />
  {:else if s.must_change_password}<StatusBadge tone="warning" label="Temporary password" help="Hasn't chosen their own password yet." />
  {:else}<StatusBadge tone="success" label="Active" />{/if}
{/snippet}

<PageHeader compact={embedded} eyebrow="Administration" title={session.isPlatform ? "Platform staff" : "Staff"}
            description={session.isPlatform ? "People who run the CIDMS platform." : "Everyone who works in the centre, and what each person can do."}>
  {#snippet actions()}<Button variant="primary" icon="plus" onclick={openAdd}>Add a person</Button>{/snippet}
</PageHeader>

<section class="card" aria-label="Staff">
  <FilterBar placeholder="Search by name, email or mobile…" searchLabel="Search staff" inlineKeys={["active"]}>
    {#snippet inline()}
      <label class="sr-only" for="active">Show</label>
      <select id="active" class="select" value={active} onchange={(e) => setQuery({ active: e.currentTarget.value === "true" ? null : e.currentTarget.value, page: null })}>
        <option value="true">Active people</option>
        <option value="false">Deactivated</option>
        <option value="all">Everyone</option>
      </select>
    {/snippet}
  </FilterBar>
  <DataTable label="Staff" rows={data?.items ?? []} {loading} error={loadError} onretry={() => reload++} page={data}
             actions={actionsFor} actionsLabel={(s) => `Actions for ${s.full_name}`} onrowclick={openEdit}
             empty={{ icon: "users", title: search ? "Nobody matches that search." : "Nobody here yet." }}
             columns={[
               { key: "person", label: "Person", cell: personCell, mobile: "title" },
               { key: "mobile", label: "Mobile", value: (s) => formatPhone(s.mobile) || "—", class: "tabular", nowrap: true },
               { key: "roles", label: "Roles", cell: rolesCell, mobile: "sub", tip: ROLE_TIP },
               { key: "status", label: "Status", cell: statusCell, mobile: "end" },
               { key: "last", label: "Last sign-in", value: (s) => dateTime(s.last_login_at), optional: true, class: "text-sm" },
             ]} />
</section>

<Dialog bind:open={dialogOpen} title={editing ? `Edit ${editing.full_name}` : "Add a person"} icon={editing ? "edit" : "user"} tone="info"
        description={editing ? "" : "They get a temporary password and choose their own the first time they sign in."}>
  <form id="staff-form" class="stack" onsubmit={submitting(form, "Couldn't save")} novalidate>
    <FormErrors {form} {labels} idPrefix="s_" />
    <Field id="s_full_name" label="Full name" required error={form.error("full_name")}>
      {#snippet children({ invalid, describedby })}
        <input id="s_full_name" class="input" autocomplete="off" bind:value={form.values.full_name} {...form.field("full_name")} aria-invalid={invalid} aria-describedby={describedby} />
      {/snippet}
    </Field>
    <div class="form-grid">
      <Field id="s_email" label="Email" required={!editing} error={form.error("email")} hint={editing ? "Email can't be changed." : "They sign in with it."}>
        {#snippet children({ invalid, describedby })}
          <input id="s_email" class="input" type="email" autocomplete="off" bind:value={form.values.email} disabled={!!editing} {...form.field("email")}
                 aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
      <Field id="s_mobile" label="Mobile" optional error={form.error("mobile")}>
        {#snippet children({ invalid, describedby })}
          {@const f = form.field("mobile")}
          <PhoneInput id="s_mobile" bind:value={form.values.mobile} {invalid} {describedby} onblur={f.onblur} oninput={f.oninput} />
        {/snippet}
      </Field>
    </div>
    <fieldset class="field roles-field" id="s_role_ids" tabindex="-1">
      <legend class="label roles-legend">Roles<span class="req" aria-hidden="true">*</span> <InfoTip text={ROLE_TIP} about="roles" /></legend>
      {#each roles as r (r.id)}
        <label class="check-row check-top">
          <input class="checkbox" type="checkbox" checked={form.values.role_ids.includes(r.id)} onchange={(e) => toggleRole(r.id, e.currentTarget.checked)} />
          <span><span class="font-semibold">{r.name}</span> <span class="text-muted">· {r.description}</span></span>
        </label>
      {/each}
      {#if form.error("role_ids")}<p class="field-error"><Icon name="alert" size="sm" />{form.error("role_ids")}</p>{/if}
    </fieldset>
    {#if !editing}
      <Field id="s_temporary_password" label="Temporary password" required error={form.error("temporary_password")}
             tip="A random password, different for each person. Tell them this password: it works once, and at their first sign-in they must choose their own.">
        {#snippet children({ invalid, describedby })}
          <div class="row">
            <input id="s_temporary_password" class="input mono" bind:value={form.values.temporary_password} {...form.field("temporary_password")}
                   aria-invalid={invalid} aria-describedby={describedby} />
            <IconButton icon="refresh" label="Make another random password" variant="outline" onclick={() => (form.values.temporary_password = generatePassword())} />
          </div>
        {/snippet}
      </Field>
    {:else}
      <label class="check-row check-top">
        <input class="checkbox" type="checkbox" bind:checked={form.values.is_active} disabled={editing.id === session.me?.id} />
        <span><span class="font-semibold">Active</span> <span class="text-muted">· deactivating signs them out everywhere; their history stays.</span></span>
      </label>
      {#if form.error("is_active")}<p class="field-error"><Icon name="alert" size="sm" />{form.error("is_active")}</p>{/if}
    {/if}
  </form>
  {#snippet footer()}
    {#if editing}{@const who = editing}<Button variant="ghost-destructive" class="push-left" icon="lock" size="sm" onclick={() => resetPassword(who)}>Reset password</Button>{/if}
    <Button onclick={() => (dialogOpen = false)}>Cancel</Button>
    <Button variant="primary" type="submit" form="staff-form" loading={form.submitting} loadingText="Saving…">{editing ? "Save changes" : "Add person"}</Button>
  {/snippet}
</Dialog>

<Dialog open={!!shownPassword} onclose={() => (shownPassword = null)} title={shownPassword?.reset ? "Password reset" : "Person added"} icon="check" tone="success"
        description={shownPassword ? `For ${shownPassword.name}. Copy it now and give it to them.` : ""}>
  {#if shownPassword}
    <div class="stack-sm">
      <div class="alert alert-warning" role="alert"><Icon name="alert" /><div>This password won't be shown again
        {shownPassword.reset ? "— they've been signed out everywhere" : ""}. They choose their own the first time they sign in.</div></div>
      <div class="code-box">
        <pre class="mono" aria-label="Temporary password">{shownPassword.password}</pre>
        <button type="button" class="btn btn-outline btn-icon btn-sm" aria-label="Copy the password" use:tooltip={pwCopied ? "Copied" : "Copy the password"}
                onclick={copyPassword}><Icon name={pwCopied ? "check" : "clipboard"} size="sm" /></button>
      </div>
    </div>
  {/if}
  {#snippet footer()}<Button variant="primary" onclick={() => (shownPassword = null)}>{pwCopied ? "Done" : "I've saved it"}</Button>{/snippet}
</Dialog>

<style>
  .person { gap: 10px; min-width: 0; }
  .roles { gap: 6px; }
  .roles-field { border: 0; padding: 0; margin: 0; outline: none; }
  .roles-legend { display: inline-flex; align-items: center; gap: 2px; margin-bottom: 6px; padding: 0; }
  :global(.push-left) { margin-right: auto; }
  @media (max-width: 640px) { :global(.push-left) { margin-right: 0; flex: 1 1 100% !important; } }
</style>
