<script lang="ts">
  import Dialog from "../../components/Dialog.svelte";
  import Field from "../../components/Field.svelte";
  import Pagination from "../../components/Pagination.svelte";
  import { ApiError, get, patch, post } from "../../lib/api";
  import { date, rupees } from "../../lib/format";
  import { router, setQuery } from "../../lib/router.svelte";
  import { session } from "../../lib/session.svelte";
  import { toastError, toasts } from "../../lib/toast.svelte";
  import type { Client, Page, Plan } from "../../lib/types";

  const SIZE = 25;
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
      toasts.show(`${c.name} added. The owner signs in at ${c.slug}.${host} with the temporary password ${form.owner_temporary_password}.`, "info");
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
    if (next === "suspended" && !confirm(`Suspend ${c.name}? Everyone there is signed out and can't sign in until you reactivate it.`)) return;
    try {
      await patch(`/api/platform/clients/${c.id}`, { status: next });
      toasts.show(`${c.name} ${next === "active" ? "reactivated" : "suspended"}.`);
      reload++;
    } catch (e) {
      toastError(e);
    }
  }
</script>

<div class="stack">
  <div class="toolbar">
    <h1 class="grow">Clients</h1>
    {#if canManage}<button class="btn primary" onclick={openAdd}>Add a client</button>{/if}
  </div>
  <div class="card">
    <div class="toolbar filters">
      <label class="sr-only" for="search">Search clients</label>
      <input id="search" type="search" placeholder="Search by name or address" bind:value={searchText} oninput={onSearch} />
      <label class="sr-only" for="status">Status</label>
      <select id="status" value={status} onchange={(e) => setQuery({ status: e.currentTarget.value, page: null })}>
        <option value="">All</option><option value="active">Active</option><option value="suspended">Suspended</option>
      </select>
    </div>
    {#if loadError}
      <div class="alert" role="alert">{loadError}</div>
    {:else if data}
      <div class="table-wrap">
        <table class="data">
          <thead><tr><th>Client</th><th>Type</th><th>Plan</th><th>Paid until</th><th>Status</th><th><span class="sr-only">Actions</span></th></tr></thead>
          <tbody>
            {#each data.items as c (c.id)}
              <tr>
                <td><strong>{c.name}</strong><div class="muted mono">{c.slug}.{host}</div></td>
                <td>{({ diagnostic: "Diagnostic centre", opd: "OPD", clinic: "Clinic" })[c.kind]}</td>
                <td>{c.plan ? `${c.plan.name} · ${rupees(c.plan.price_monthly)}/month` : "—"}</td>
                <td>{date(c.paid_until)}</td>
                <td><span class="badge {c.status === 'active' ? 'good' : 'bad'}">{c.status === "active" ? "Active" : "Suspended"}</span></td>
                <td>
                  {#if canManage}
                    {#if c.status === "active"}
                      <button class="btn small danger" onclick={() => setStatus(c, "suspended")}>Suspend</button>
                    {:else}
                      <button class="btn small" onclick={() => setStatus(c, "active")}>Reactivate</button>
                    {/if}
                  {/if}
                </td>
              </tr>
            {:else}
              <tr><td colspan="6" class="muted empty">No clients yet.</td></tr>
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

<Dialog bind:open={addOpen} title="Add a client" wide>
  <form id="client-form" class="stack" onsubmit={(e) => { e.preventDefault(); create(); }} novalidate>
    <div class="row-2">
      <Field id="name" label="Centre name" required error={errors.name}>
        {#snippet children({ invalid, describedby })}<input id="name" bind:value={form.name} oninput={suggestSlug} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
      </Field>
      <Field id="slug" label="Address" required error={errors.slug} hint="{form.slug || 'name'}.{host}">
        {#snippet children({ invalid, describedby })}<input id="slug" class="mono" bind:value={form.slug} oninput={() => (slugEdited = true)} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
      </Field>
    </div>
    <div class="row-2">
      <Field id="kind" label="Type" error={errors.kind}>
        {#snippet children()}<select id="kind" bind:value={form.kind}><option value="diagnostic">Diagnostic centre</option><option value="opd">OPD</option><option value="clinic">Clinic</option></select>{/snippet}
      </Field>
      <Field id="plan" label="Plan" error={errors.plan_id}>
        {#snippet children()}
          <select id="plan" bind:value={form.plan_id}>
            <option value="">No plan yet</option>
            {#each plans as p (p.id)}<option value={p.id}>{p.name} · {rupees(p.price_monthly)}/month · {p.max_users} staff</option>{/each}
          </select>
        {/snippet}
      </Field>
    </div>
    <h2>Owner</h2>
    <div class="row-2">
      <Field id="owner_name" label="Owner's name" required error={errors.owner_name}>
        {#snippet children({ invalid, describedby })}<input id="owner_name" bind:value={form.owner_name} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
      </Field>
      <Field id="owner_email" label="Owner's email" required error={errors.owner_email}>
        {#snippet children({ invalid, describedby })}<input id="owner_email" type="email" bind:value={form.owner_email} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
      </Field>
    </div>
    <Field id="owner_pw" label="Temporary password" required error={errors.owner_temporary_password} hint="They choose their own at first sign-in.">
      {#snippet children({ invalid, describedby })}<input id="owner_pw" class="mono" bind:value={form.owner_temporary_password} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
    </Field>
  </form>
  {#snippet footer()}
    <button class="btn" onclick={() => (addOpen = false)}>Cancel</button>
    <button class="btn primary" type="submit" form="client-form" disabled={saving}>{saving ? "Adding…" : "Add client"}</button>
  {/snippet}
</Dialog>

<style>
  .filters { padding: 12px; border-bottom: 1px solid var(--border); }
  .filters input { max-width: 360px; }
  .filters select { width: auto; }
  .table-wrap { overflow-x: auto; }
  .empty { padding: 24px; text-align: center; }
</style>
