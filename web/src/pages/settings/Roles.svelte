<script lang="ts">
  // Settings > Roles & permissions: the built-in roles (read-only, can be copied) and the centre's own roles,
  // what each can do, who has each one, and a side-by-side comparison. The server checks every rule; this page
  // mirrors them so people see why something is locked before they try it.
  let { embedded = true }: { embedded?: boolean; params?: Record<string, string> } = $props();
  import { z } from "zod";
  import Button from "../../components/Button.svelte";
  import Dialog from "../../components/Dialog.svelte";
  import EmptyState from "../../components/EmptyState.svelte";
  import Field from "../../components/Field.svelte";
  import FormErrors from "../../components/FormErrors.svelte";
  import Icon from "../../components/Icon.svelte";
  import IconButton from "../../components/IconButton.svelte";
  import InfoTip from "../../components/InfoTip.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import { api, get, post } from "../../lib/api";
  import { confirmDialog } from "../../lib/confirm.svelte";
  import { Form } from "../../lib/form.svelte";
  import { dateTime } from "../../lib/format";
  import { confirmLeave } from "../../lib/leave";
  import { router, setBeforeLeave, setQuery } from "../../lib/router.svelte";
  import { optionalText, submitting, text } from "../../lib/schemas";
  import { session } from "../../lib/session.svelte";
  import { notify, notifyError } from "../../lib/toast.svelte";
  import { tooltip } from "../../lib/tooltip";

  interface RoleRow {
    id: string; code: string; name: string; description: string; scope: string; is_builtin: boolean;
    permissions: string[]; member_count: number; editable: boolean; assignable: boolean; locked_reason: string;
    created_by_name: string; created_at: string | null; updated_at: string | null;
  }
  interface Perm { code: string; label: string; description: string; held: boolean }
  interface Group { key: string; label: string; description: string; permissions: Perm[] }
  interface Member { id: string; full_name: string; email: string; is_active: boolean; avatar_url: string }

  const BUILTIN_TIP = "Built-in roles can't be changed — copy one to customise.";
  const NOT_HELD_TIP = "You can only give permissions you have yourself.";
  const NEW = "new";

  let roles = $state<RoleRow[]>([]);
  let groups = $state<Group[]>([]);
  let loadError = $state("");
  let loaded = $state(false);
  let members = $state<Member[]>([]);
  let membersLoading = $state(false);
  let search = $state("");

  const canManage = $derived(session.can("roles.manage") && !session.isPlatform);
  const selectedId = $derived(router.query.get("role") ?? "");
  const view = $derived(router.query.get("view") === "compare" ? "compare" : "edit");
  const selected = $derived(roles.find((r) => r.id === selectedId) ?? null);
  const isNew = $derived(selectedId === NEW && canManage);
  const editable = $derived(isNew || (!!selected && selected.editable && canManage));
  const builtins = $derived(roles.filter((r) => r.is_builtin));
  const custom = $derived(roles.filter((r) => !r.is_builtin));
  const allPerms = $derived(groups.flatMap((g) => g.permissions));
  const held = $derived(new Set(allPerms.filter((p) => p.held).map((p) => p.code)));

  // ---------- loading ----------
  async function load(select?: string) {
    try {
      const [r, g] = await Promise.all([get<RoleRow[]>("/api/roles"), get<Group[]>("/api/permissions")]);
      roles = r;
      groups = g;
      loadError = "";
      loaded = true;
      const want = select ?? selectedId;
      if (want !== NEW && !r.some((x) => x.id === want) && r.length) setQuery({ role: r[0].id });
      else if (select) setQuery({ role: select });
    } catch (e) {
      loadError = (e as Error).message;
    }
  }
  $effect(() => { load(); });

  // ---------- the form ----------
  const schema = z.object({
    name: text("Give the role a name.", 100, 2),
    description: optionalText(300),
    permissions: z.array(z.string()),
  });
  const blank = { name: "", description: "", permissions: [] as string[] };
  const labels = { name: "Name", description: "Description", permissions: "Permissions" };
  let baseline = $state(JSON.stringify(blank));
  const snapshot = (v: { name: string; description: string; permissions: string[] }) =>
    JSON.stringify({ name: v.name.trim(), description: v.description.trim(), permissions: [...v.permissions].sort() });

  const form = new Form({
    schema, initial: blank,
    rules: (v, add) => { if (!v.permissions.length) add("permissions", "Choose at least one permission."); },
    onSubmit: async (v) => {
      const body = { name: v.name, description: v.description, permissions: [...v.permissions].sort() };
      const saved = isNew ? await post<RoleRow>("/api/roles", body) : await api<RoleRow>("PUT", `/api/roles/${selectedId}`, { body });
      baseline = snapshot(body);
      notify(isNew ? `Role "${saved.name}" created.` : `Role "${saved.name}" saved. It applies to everyone with it straight away.`);
      await load(saved.id);
    },
  });
  const dirty = $derived(editable && snapshot(form.values) !== baseline);

  // Put the chosen role into the form (or a blank one for a new role).
  let shownFor = "";
  $effect(() => {
    const key = isNew ? NEW : selected ? `${selected.id}:${selected.updated_at}:${selected.permissions.join(",")}` : "";
    if (key === shownFor) return;
    shownFor = key;
    const v = isNew || !selected ? blank : { name: selected.name, description: selected.description, permissions: [...selected.permissions] };
    form.reset(v);
    baseline = snapshot(v);
  });

  // Who has the role.
  $effect(() => {
    const id = selected?.id;
    members = [];
    if (!id) return;
    const ctrl = new AbortController();
    membersLoading = true;
    get<Member[]>(`/api/roles/${id}/members`, undefined, ctrl.signal)
      .then((m) => (members = m))
      .catch((e) => { if (e.name !== "AbortError") notifyError(e, { title: "Couldn't load who has this role" }); })
      .finally(() => (membersLoading = false));
    return () => ctrl.abort();
  });

  // Ask before leaving with unsaved changes (moving inside the app, or closing the tab).
  $effect(() => {
    setBeforeLeave(dirty ? confirmLeave({ message: "Your changes to this role aren't saved. If you leave now, they're lost." }) : null);
    const onUnload = (e: BeforeUnloadEvent) => { if (dirty) e.preventDefault(); };
    window.addEventListener("beforeunload", onUnload);
    return () => { window.removeEventListener("beforeunload", onUnload); setBeforeLeave(null); };
  });

  async function choose(id: string, nextView: "edit" | "compare" = "edit") {
    if (id === selectedId && nextView === view) return;
    if (dirty && !(await confirmDialog({ title: "Discard your changes?", message: "You haven't saved the changes to this role.",
                                        confirmLabel: "Discard changes", tone: "danger" }))) return;
    shownFor = "";
    setQuery({ role: id || null, view: nextView === "compare" ? "compare" : null });
  }

  function cancel() {
    if (isNew) { choose(roles[0]?.id ?? ""); return; }
    shownFor = "";
    const v = selected ? { name: selected.name, description: selected.description, permissions: [...selected.permissions] } : blank;
    form.reset(v);
    baseline = snapshot(v);
  }

  // ---------- the permission matrix ----------
  const q = $derived(search.trim().toLowerCase());
  const matches = (p: Perm) => !q || `${p.label} ${p.description} ${p.code}`.toLowerCase().includes(q);
  const shownGroups = $derived(groups.map((g) => ({ ...g, permissions: g.permissions.filter(matches) })).filter((g) => g.permissions.length));
  const has = (code: string) => form.values.permissions.includes(code);
  const canToggle = (p: Perm) => editable && p.held;
  const whyLocked = (p: Perm) => !canManage ? "You can look, but only someone who can manage roles can change them."
    : !editable ? (selected?.locked_reason || BUILTIN_TIP) : !p.held ? NOT_HELD_TIP : "";

  function toggle(code: string, on: boolean) {
    const set = new Set(form.values.permissions);
    if (on) set.add(code); else set.delete(code);
    form.values.permissions = [...set];
    form.touched.permissions = true;
    form.validate();
  }

  function groupState(g: Group): "all" | "some" | "none" {
    const n = g.permissions.filter((p) => has(p.code)).length;
    return n === 0 ? "none" : n === g.permissions.length ? "all" : "some";
  }

  function toggleGroup(g: Group) {
    const togglable = g.permissions.filter(canToggle);
    const allOn = togglable.every((p) => has(p.code));
    const set = new Set(form.values.permissions);
    for (const p of togglable) { if (allOn) set.delete(p.code); else set.add(p.code); }
    form.values.permissions = [...set];
    form.touched.permissions = true;
    form.validate();
  }

  /** A checkbox that can show "some of these" (the group's select-all). */
  function tri(node: HTMLInputElement, state: "all" | "some" | "none") {
    const set = (s: typeof state) => { node.indeterminate = s === "some"; node.checked = s === "all"; };
    set(state);
    return { update: set };
  }

  // ---------- copy and delete ----------
  let busy = $state(false);

  async function copy(role: RoleRow) {
    if (dirty && !(await confirmDialog({ title: "Discard your changes?", message: "You haven't saved the changes to this role.",
                                        confirmLabel: "Discard and copy", tone: "danger" }))) return;
    busy = true;
    try {
      const made = await post<RoleRow>(`/api/roles/${role.id}/copy`, {});
      shownFor = "";
      notify(`"${made.name}" created from ${role.name}. Change what it can do, then save.`);
      await load(made.id);
    } catch (e) {
      notifyError(e, { title: "Couldn't copy the role" });
    } finally {
      busy = false;
    }
  }

  let reassignOpen = $state(false);
  let reassignTo = $state("");
  const reassignChoices = $derived(roles.filter((r) => r.id !== selected?.id && r.assignable));

  async function startDelete() {
    if (!selected) return;
    if (members.length) {
      reassignTo = reassignChoices[0]?.id ?? "";
      reassignOpen = true;
      return;
    }
    if (!(await confirmDialog({ title: `Delete "${selected.name}"?`, confirmLabel: "Delete role", tone: "danger",
                                message: "Nobody has this role. It's removed for good; the activity log keeps a record of it." }))) return;
    await remove(null);
  }

  async function remove(target: string | null) {
    if (!selected) return;
    const name = selected.name;
    busy = true;
    try {
      await api("DELETE", `/api/roles/${selected.id}`, { query: { reassign_to: target } });
      reassignOpen = false;
      baseline = snapshot(form.values); // nothing left to save
      notify(target ? `"${name}" deleted. Its people now have ${roles.find((r) => r.id === target)?.name}.` : `"${name}" deleted.`);
      setQuery({ role: null });
      await load();
    } catch (e) {
      notifyError(e, { title: "Couldn't delete the role" });
    } finally {
      busy = false;
    }
  }

  const initials = (name: string) => name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  const countLabel = (n: number) => `${n} ${n === 1 ? "person" : "people"}`;
  const PAGE_TIP = "A role is a set of permissions. Give people one or more roles in Staff. Built-in roles are kept up to date by CIDMS; copy one to make your own version.";
</script>

{#snippet roleItem(r: RoleRow)}
  <li>
    <button type="button" class="role-item" class:is-active={r.id === selectedId && view === "edit"} aria-current={r.id === selectedId && view === "edit" ? "true" : undefined}
            onclick={() => choose(r.id)}>
      <span class="role-item-main">
        <span class="role-item-name">{r.name}</span>
        {#if r.description}<span class="role-item-desc">{r.description}</span>{/if}
      </span>
      <span class="role-item-meta">
        {#if r.is_builtin}<span class="lock-badge" use:tooltip={BUILTIN_TIP} aria-label="Built-in role"><Icon name="lock" size="sm" /></span>{/if}
        <span class="count" use:tooltip={`${countLabel(r.member_count)} with this role (active staff)`}>
          <Icon name="users" size="sm" />{r.member_count}<span class="sr-only"> people</span></span>
      </span>
    </button>
  </li>
{/snippet}

<PageHeader compact={embedded} eyebrow="Settings" title="Roles & permissions" tip={PAGE_TIP}
            description="What each role can see and do. Changes apply to everyone with the role on their next click.">
  {#snippet actions()}
    <Button variant={view === "compare" ? "secondary" : "outline"} icon="sheet" onclick={() => choose(selectedId, view === "compare" ? "edit" : "compare")}
            tooltip="See every role's permissions side by side">{view === "compare" ? "Back to editing" : "Compare roles"}</Button>
    {#if canManage}<Button variant="primary" icon="plus" onclick={() => choose(NEW)}>New role</Button>{/if}
  {/snippet}
</PageHeader>

{#if loadError}
  <div class="alert alert-destructive" role="alert"><Icon name="alert" /><div>{loadError} <Button size="sm" onclick={() => load()}>Try again</Button></div></div>
{:else if !loaded}
  <div class="card"><div class="card-content text-muted">Loading roles…</div></div>
{:else if view === "compare"}
  <!-- ---------- compare: roles across, permissions down ---------- -->
  <section class="card compare-card" aria-labelledby="compare-title">
    <div class="card-header">
      <div class="grow"><h2 class="card-title" id="compare-title">Compare roles</h2>
        <p class="card-description">Every role's permissions side by side. Read-only; choose a role to change it.</p></div>
      <div class="input-group compare-search"><Icon name="search" /><label class="sr-only" for="cmp-search">Filter permissions</label>
        <input id="cmp-search" class="input" type="search" placeholder="Filter permissions…" bind:value={search} /></div>
    </div>
    <!-- A scrolling region must be reachable by keyboard so it can be scrolled with the arrow keys (WCAG 2.1.1). -->
    <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
    <div class="compare-scroll" tabindex="0" role="region" aria-label="Roles and their permissions (scrolls sideways)">
      <table class="compare">
        <thead>
          <tr>
            <th scope="col" class="corner">Permission</th>
            {#each roles as r (r.id)}
              <th scope="col" class="role-col">
                <button type="button" class="role-col-btn" onclick={() => choose(r.id)} use:tooltip={r.description || r.name}>
                  {#if r.is_builtin}<Icon name="lock" size="sm" />{/if}{r.name}</button>
              </th>
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each shownGroups as g (g.key)}
            <tr class="group-row"><th scope="rowgroup" colspan={roles.length + 1}><span class="sticky-label">{g.label}</span></th></tr>
            {#each g.permissions as p (p.code)}
              <tr>
                <th scope="row" class="perm-col"><span use:tooltip={p.description}>{p.label}</span></th>
                {#each roles as r (r.id)}
                  <td class="cell">{#if r.permissions.includes(p.code)}<span class="yes" use:tooltip={`${r.name}: ${p.label}`}><Icon name="check" size="sm" /><span class="sr-only">Yes</span></span>{:else}<span class="no" aria-label="No">–</span>{/if}</td>
                {/each}
              </tr>
            {/each}
          {/each}
        </tbody>
      </table>
      {#if !shownGroups.length}<EmptyState compact icon="search" title="No permission matches that filter." />{/if}
    </div>
  </section>
{:else}
  <div class="roles-layout">
    <!-- ---------- the list (a select on phones) ---------- -->
    <nav class="card roles-list" aria-label="Roles">
      <div class="list-section">
        <h2 class="list-title">Built-in <InfoTip text={BUILTIN_TIP} about="built-in roles" /></h2>
        <ul>{#each builtins as r (r.id)}{@render roleItem(r)}{/each}</ul>
      </div>
      <div class="list-section">
        <h2 class="list-title">Your centre's roles</h2>
        {#if custom.length}<ul>{#each custom as r (r.id)}{@render roleItem(r)}{/each}</ul>
        {:else}<p class="text-sm text-muted list-empty">None yet. Make one with New role, or copy a built-in role.</p>{/if}
        {#if isNew}<ul><li><span class="role-item is-active" aria-current="true"><span class="role-item-name">New role</span></span></li></ul>{/if}
      </div>
    </nav>
    <div class="roles-select">
      <label class="label" for="role-pick">Role</label>
      <select id="role-pick" class="select" value={selectedId} onchange={(e) => choose(e.currentTarget.value)}>
        {#if isNew}<option value={NEW}>New role</option>{/if}
        <optgroup label="Built-in (copy to customise)">{#each builtins as r (r.id)}<option value={r.id}>{r.name} · {countLabel(r.member_count)}</option>{/each}</optgroup>
        {#if custom.length}<optgroup label="Your centre's roles">{#each custom as r (r.id)}<option value={r.id}>{r.name} · {countLabel(r.member_count)}</option>{/each}</optgroup>{/if}
      </select>
    </div>

    <!-- ---------- the chosen role ---------- -->
    <div class="role-detail">
      {#if !selected && !isNew}
        <div class="card"><EmptyState icon="shield" title="Choose a role to see what it can do." /></div>
      {:else}
        <form class="card" onsubmit={submitting(form, "Couldn't save the role")} novalidate aria-labelledby="role-title">
          <div class="card-header">
            <div class="grow">
              <h2 class="card-title" id="role-title">
                {isNew ? "New role" : selected?.name}
                {#if selected?.is_builtin}<span class="badge badge-plain builtin-badge" use:tooltip={BUILTIN_TIP}><Icon name="lock" size="sm" /> Built-in</span>{/if}
              </h2>
              {#if selected && !selected.is_builtin && selected.updated_at}
                <p class="card-description">{selected.created_by_name ? `Made by ${selected.created_by_name}. ` : ""}Last changed {dateTime(selected.updated_at)}.</p>
              {/if}
            </div>
            {#if selected && canManage}
              <div class="card-actions">
                <IconButton icon="layers" label="Copy this role into a new one" variant="outline" disabled={busy} onclick={() => copy(selected!)} />
                {#if !selected.is_builtin}
                  <IconButton icon="x" label={selected.editable ? "Delete this role" : selected.locked_reason} variant="ghost-destructive"
                              disabled={busy || !selected.editable} onclick={startDelete} />
                {/if}
              </div>
            {/if}
          </div>

          <div class="card-content stack">
            {#if selected && !editable}
              <div class="alert alert-info" role="note"><Icon name="lock" />
                <div class="grow">{canManage ? (selected.locked_reason || BUILTIN_TIP) : "You can look, but only someone who can manage roles can change them."}
                  {#if canManage && selected.is_builtin}<Button size="sm" icon="layers" class="ml" onclick={() => copy(selected!)} disabled={busy}>Copy to customise</Button>{/if}</div>
              </div>
            {/if}
            <FormErrors {form} {labels} idPrefix="r_" />
            <div class="grid-2 name-grid">
              <Field id="r_name" label="Name" required={editable} error={form.error("name")} tip="What people see in Staff when they give someone this role. Each role's name must be different.">
                {#snippet children({ invalid, describedby })}
                  <input id="r_name" class="input" maxlength="100" autocomplete="off" disabled={!editable} bind:value={form.values.name} {...form.field("name")}
                         aria-invalid={invalid} aria-describedby={describedby} />
                {/snippet}
              </Field>
              <Field id="r_description" label="Description" optional error={form.error("description")} tip="One line on who this role is for, shown next to the role in Staff.">
                {#snippet children({ invalid, describedby })}
                  <input id="r_description" class="input" maxlength="300" autocomplete="off" disabled={!editable} bind:value={form.values.description} {...form.field("description")}
                         aria-invalid={invalid} aria-describedby={describedby} />
                {/snippet}
              </Field>
            </div>

            <fieldset class="perms" id="r_permissions" tabindex="-1" aria-describedby={form.error("permissions") ? "r_permissions-error" : undefined}>
              <legend class="label perms-legend">Permissions <span class="text-muted perm-count">· {form.values.permissions.length} of {allPerms.length}</span>
                <InfoTip text="Tick what people with this role may do. You can only give permissions you have yourself; the others are greyed out." about="permissions" /></legend>
              <div class="perms-head">
                <div class="input-group perm-search"><Icon name="search" /><label class="sr-only" for="perm-search">Filter permissions</label>
                  <input id="perm-search" class="input input-sm" type="search" placeholder="Filter permissions…" bind:value={search} /></div>
              </div>
              {#if form.error("permissions")}<p id="r_permissions-error" class="field-error"><Icon name="alert" size="sm" />{form.error("permissions")}</p>{/if}

              <div class="groups">
                {#each shownGroups as g (g.key)}
                  {@const st = groupState(g)}
                  {@const anyTogglable = g.permissions.some(canToggle)}
                  <section class="group" aria-labelledby="g-{g.key}">
                    <div class="group-head">
                      <label class="check-row group-check" use:tooltip={anyTogglable ? (st === "all" ? `Untick all in ${g.label}` : `Tick all in ${g.label}`) : whyLocked(g.permissions[0])}>
                        <input class="checkbox" type="checkbox" use:tri={st} disabled={!anyTogglable} onchange={() => toggleGroup(g)}
                               aria-label="All of {g.label}" />
                        <span id="g-{g.key}" class="font-semibold">{g.label}</span>
                      </label>
                      <span class="group-desc text-sm text-muted">{g.description}</span>
                    </div>
                    <ul class="perm-list">
                      {#each g.permissions as p (p.code)}
                        {@const locked = !canToggle(p)}
                        <li class="perm" class:is-locked={locked}>
                          <label class="check-row check-top perm-label" use:tooltip={locked ? whyLocked(p) : ""}>
                            <input class="checkbox" type="checkbox" checked={has(p.code)} disabled={locked}
                                   onchange={(e) => toggle(p.code, e.currentTarget.checked)} />
                            <span class="perm-text">{p.label}{#if !p.held && editable}<span class="sr-only"> ({NOT_HELD_TIP})</span>{/if}</span>
                          </label>
                          <InfoTip text={p.description} about={p.label} />
                        </li>
                      {/each}
                    </ul>
                  </section>
                {/each}
                {#if !shownGroups.length}<EmptyState compact icon="search" title="No permission matches that filter." />{/if}
              </div>
            </fieldset>
          </div>

          {#if editable}
            <div class="card-footer row justify-end form-foot">
              {#if dirty}<span class="text-sm text-muted push">Unsaved changes</span>{/if}
              <Button onclick={cancel} disabled={form.submitting || (!dirty && !isNew)}>Cancel</Button>
              <Button variant="primary" type="submit" loading={form.submitting} loadingText="Saving…" disabled={!dirty && !isNew}>{isNew ? "Create role" : "Save changes"}</Button>
            </div>
          {/if}
        </form>

        {#if selected}
          <section class="card" aria-labelledby="members-title">
            <div class="card-header"><div class="grow">
              <h2 class="card-title" id="members-title">Who has this role</h2>
              <p class="card-description">{membersLoading ? "Loading…" : members.length ? countLabel(members.length) : "Nobody yet. Give people roles in Staff."}</p>
            </div><div class="card-actions"><Button size="sm" href="/settings/staff" icon="users">Open Staff</Button></div></div>
            {#if members.length}
              <ul class="members">
                {#each members as m (m.id)}
                  <li><a class="member" href="/settings/staff?search={encodeURIComponent(m.email)}" use:tooltip={`Open ${m.full_name} in Staff`}>
                    {#if m.avatar_url}<img class="avatar avatar-sm" src={m.avatar_url} alt="" />{:else}<span class="avatar avatar-sm" aria-hidden="true">{initials(m.full_name)}</span>{/if}
                    <span class="grow member-text"><span class="cell-title">{m.full_name}</span><span class="cell-sub truncate">{m.email}</span></span>
                    {#if !m.is_active}<span class="badge badge-destructive" use:tooltip={"Deactivated: can't sign in"}>Deactivated</span>{/if}
                  </a></li>
                {/each}
              </ul>
            {/if}
          </section>
        {/if}
      {/if}
    </div>
  </div>
{/if}

<Dialog bind:open={reassignOpen} title={`Delete "${selected?.name ?? ""}"?`} icon="alert" tone="destructive"
        description={`${countLabel(members.length)} ${members.length === 1 ? "has" : "have"} this role. Choose the role to give them instead; then it's deleted.`}>
  <Field id="reassign" label="Give them this role instead" required tip="Only roles you're allowed to give are listed. They keep any other roles they already have.">
    {#snippet children({ describedby })}
      <select id="reassign" class="select" bind:value={reassignTo} aria-describedby={describedby}>
        {#each reassignChoices as r (r.id)}<option value={r.id}>{r.name}</option>{/each}
      </select>
    {/snippet}
  </Field>
  {#snippet footer()}
    <Button onclick={() => (reassignOpen = false)}>Cancel</Button>
    <Button variant="destructive" loading={busy} loadingText="Deleting…" disabled={!reassignTo} onclick={() => remove(reassignTo)}>Move them and delete</Button>
  {/snippet}
</Dialog>

<style src="./styles/Roles.css"></style>
