<script lang="ts">
  import Dialog from "../../components/Dialog.svelte";
  import Field from "../../components/Field.svelte";
  import Icon from "../../components/Icon.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import Pagination from "../../components/Pagination.svelte";
  import { ApiError, get, patch, post } from "../../lib/api";
  import { date, rupees } from "../../lib/format";
  import { router, setQuery } from "../../lib/router.svelte";
  import { session } from "../../lib/session.svelte";
  import { notify, toastError } from "../../lib/toast.svelte";
  import { confirmDialog } from "../../lib/confirm.svelte";
  import type { Client, Page, Plan } from "../../lib/types";

  const SIZE = $derived(Math.min(100, Number(router.query.get("size")) || 25));
  const page = $derived(Number(router.query.get("page") ?? 1) || 1);
  const search = $derived(router.query.get("search") ?? "");
  const status = $derived(router.query.get("status") ?? "");
  const canManage = $derived(session.can("platform.clients.manage"));

  let data = $state<Page<Client> | null>(null);
  let plans = $state<Plan[]>([]);
  let loadError = $state("");
  let reload = $state(0);
  let searchText = $state(router.query.get("search") ?? "");

  $effect(() => {
    const ctrl = new AbortController();
    reload;
    get<Page<Client>>("/api/platform/clients", { page, size: SIZE, search, status }, ctrl.signal)
      .then((d) => { data = d; loadError = ""; })
      .catch((e) => { if (e.name !== "AbortError") loadError = e.message; });
    return () => ctrl.abort();
  });

  $effect(() => {
    get<Plan[]>("/api/platform/plans").then((p) => (plans = p)).catch(toastError);
  });

  let timer: ReturnType<typeof setTimeout>;
  const onSearch = () => { clearTimeout(timer); timer = setTimeout(() => setQuery({ search: searchText.trim(), page: null }), 300); };

  // ---------- add a client ----------
  let addOpen = $state(false);
  let saving = $state(false);
  let errors = $state<Record<string, string>>({});
  let form = $state({ name: "", slug: "", kind: "diagnostic", plan_id: "", owner_name: "", owner_email: "", owner_temporary_password: "" });
  let slugEdited = false;

  const host = location.host.replace(/^[^.]+\./, "");

  function openAdd() {
    form = { name: "", slug: "", kind: "diagnostic", plan_id: plans[0]?.id ?? "", owner_name: "", owner_email: "",
             owner_temporary_password: `Welcome-${crypto.getRandomValues(new Uint32Array(1))[0] % 90000 + 10000}` };
    errors = {};
    slugEdited = false;
    addOpen = true;
  }

  function suggestSlug() {
    if (!slugEdited) form.slug = form.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);
  }

  async function create() {
    saving = true;
    errors = {};
    try {
      const c = await post<Client>("/api/platform/clients", { ...form, plan_id: form.plan_id || null });
      notify(`The owner signs in at ${c.slug}.${host} with the temporary password ${form.owner_temporary_password}.`, { kind: "info", title: `${c.name} added`, duration: 0 });
      addOpen = false;
      reload++;
    } catch (e) {
      if (e instanceof ApiError && Object.keys(e.fieldErrors).length) errors = e.fieldErrors;
      else toastError(e);
    } finally {
      saving = false;
    }
  }

  async function setStatus(c: Client, next: "active" | "suspended") {
    if (next === "suspended" && !(await confirmDialog({ title: `Suspend ${c.name}?`, tone: "danger", confirmLabel: "Suspend",
        message: "Everyone there is signed out at once and can't sign in until you reactivate it." }))) return;
    try {
      await patch(`/api/platform/clients/${c.id}`, { status: next });
      notify(`${c.name} ${next === "active" ? "reactivated" : "suspended"}.`);
      reload++;
    } catch (e) {
      toastError(e);
    }
  }
</script>

<PageHeader eyebrow="Clients" title="Clients" description="Every centre on Supreme DMS: its address, plan and whether it's active.">
  {#snippet actions()}{#if canManage}<button class="btn btn-primary" onclick={openAdd}><Icon name="plus" /> Add a client</button>{/if}{/snippet}
</PageHeader>
<div class="stack">
  <div class="card">
    <div class="toolbar">
      <div class="input-group"><Icon name="search" />
      <label class="sr-only" for="search">Search clients</label>
      <input id="search" class="input" type="search" placeholder="Search by name or address…" bind:value={searchText} oninput={onSearch} /></div>
      <label class="sr-only" for="status">Status</label>
      <select id="status" class="select" value={status} onchange={(e) => setQuery({ status: e.currentTarget.value, page: null })}>
        <option value="">All</option><option value="active">Active</option><option value="suspended">Suspended</option>
      </select>
    </div>
    {#if loadError}
      <div class="card-content"><div class="alert alert-destructive" role="alert">{loadError}</div></div>
    {:else if data}
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>Client</th><th>Type</th><th>Plan</th><th>Paid until</th><th>Status</th><th><span class="sr-only">Actions</span></th></tr></thead>
          <tbody>
            {#each data.items as c (c.id)}
              <tr>
                <td><div class="cell-title">{c.name}</div><div class="cell-sub mono">{c.slug}.{host}</div></td>
                <td>{({ diagnostic: "Diagnostic centre", opd: "OPD", clinic: "Clinic" })[c.kind]}</td>
                <td>{c.plan ? `${c.plan.name} · ${rupees(c.plan.price_monthly)}/month` : "—"}</td>
                <td>{date(c.paid_until)}</td>
                <td><span class="badge {c.status === 'active' ? 'badge-success' : 'badge-destructive'}">{c.status === "active" ? "Active" : "Suspended"}</span></td>
                <td>
                  {#if canManage}
                    {#if c.status === "active"}
                      <button class="btn btn-ghost-destructive btn-sm" onclick={() => setStatus(c, "suspended")}>Suspend</button>
                    {:else}
                      <button class="btn btn-outline btn-sm" onclick={() => setStatus(c, "active")}>Reactivate</button>
                    {/if}
                  {/if}
                </td>
              </tr>
            {:else}
              <tr><td colspan="6"><div class="empty"><Icon name="building" />No clients yet.</div></td></tr>
            {/each}
          </tbody>
        </table>
      </div>
      <Pagination page={data.page} size={data.size} total={data.total} onchange={(p) => setQuery({ page: p }, { replace: false })} />
    {:else}
      <div class="empty" aria-busy="true">Loading…</div>
    {/if}
  </div>
</div>

<Dialog bind:open={addOpen} title="Add a client" icon="building" tone="info" description="The owner gets a temporary password and chooses their own at first sign-in." wide>
  <form id="client-form" class="stack" onsubmit={(e) => { e.preventDefault(); create(); }} novalidate>
    <div class="grid-2">
      <Field id="name" label="Centre name" required error={errors.name}>
        {#snippet children({ invalid, describedby })}<input id="name" class="input" bind:value={form.name} oninput={suggestSlug} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
      </Field>
      <Field id="slug" label="Address" required error={errors.slug} hint="{form.slug || 'name'}.{host}">
        {#snippet children({ invalid, describedby })}<input id="slug" class="input mono" bind:value={form.slug} oninput={() => (slugEdited = true)} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
      </Field>
    </div>
    <div class="grid-2">
      <Field id="kind" label="Type" error={errors.kind}>
        {#snippet children()}<select id="kind" class="select" bind:value={form.kind}><option value="diagnostic">Diagnostic centre</option><option value="opd">OPD</option><option value="clinic">Clinic</option></select>{/snippet}
      </Field>
      <Field id="plan" label="Plan" error={errors.plan_id}>
        {#snippet children()}
          <select id="plan" class="select" bind:value={form.plan_id}>
            <option value="">No plan yet</option>
            {#each plans as p (p.id)}<option value={p.id}>{p.name} · {rupees(p.price_monthly)}/month · {p.max_users} staff</option>{/each}
          </select>
        {/snippet}
      </Field>
    </div>
    <h3 class="form-section-title"><Icon name="user" /> Owner</h3>
    <div class="grid-2">
      <Field id="owner_name" label="Owner's name" required error={errors.owner_name}>
        {#snippet children({ invalid, describedby })}<input id="owner_name" class="input" bind:value={form.owner_name} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
      </Field>
      <Field id="owner_email" label="Owner's email" required error={errors.owner_email}>
        {#snippet children({ invalid, describedby })}<input id="owner_email" class="input" type="email" bind:value={form.owner_email} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
      </Field>
    </div>
    <Field id="owner_pw" label="Temporary password" required error={errors.owner_temporary_password} hint="They choose their own at first sign-in.">
      {#snippet children({ invalid, describedby })}<input id="owner_pw" class="input mono" bind:value={form.owner_temporary_password} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
    </Field>
  </form>
  {#snippet footer()}
    <button class="btn btn-outline" onclick={() => (addOpen = false)}>Cancel</button>
    <button class="btn btn-primary" type="submit" form="client-form" disabled={saving}>{saving ? "Adding…" : "Add client"}</button>
  {/snippet}
</Dialog>

