<script lang="ts">
  import { z } from "zod";
  import Button from "../../components/Button.svelte";
  import DataTable from "../../components/DataTable.svelte";
  import ClientBackupsPanel from "../../components/ClientBackupsPanel.svelte";
  import Dialog from "../../components/Dialog.svelte";
  import FormDialog from "../../components/FormDialog.svelte";
  import Field from "../../components/Field.svelte";
  import FilterBar from "../../components/FilterBar.svelte";
  import FormErrors from "../../components/FormErrors.svelte";
  import Icon from "../../components/Icon.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import StatusBadge from "../../components/StatusBadge.svelte";
  import type { RowAction } from "../../components/RowMenu.svelte";
  import { get, patch, post } from "../../lib/api";
  import { confirmDialog } from "../../lib/confirm.svelte";
  import { Form } from "../../lib/form.svelte";
  import { date, rupees } from "../../lib/format";
  import { router, setQuery } from "../../lib/router.svelte";
  import { email, submitting, text } from "../../lib/schemas";
  import { session } from "../../lib/session.svelte";
  import { notify, toastError } from "../../lib/toast.svelte";
  import { tooltip } from "../../lib/tooltip";
  import type { Client, Page, Plan } from "../../lib/types";

  const SIZE = $derived(Math.min(100, Number(router.query.get("size")) || 25));
  const page = $derived(Number(router.query.get("page") ?? 1) || 1);
  const search = $derived(router.query.get("search") ?? "");
  const status = $derived(router.query.get("status") ?? "");
  const canManage = $derived(session.can("platform.clients.manage"));
  const canBackups = $derived(session.can("platform.backups.manage"));
  let backupsOf = $state<Client | null>(null);
  let backupsOpen = $state(false);

  let data = $state<Page<Client> | null>(null);
  let plans = $state<Plan[]>([]);
  let loadError = $state("");
  let loading = $state(false);
  let reload = $state(0);

  $effect(() => {
    const ctrl = new AbortController();
    const query = { page, size: SIZE, search, status };
    reload;
    loading = true;
    get<Page<Client>>("/api/platform/clients", query, ctrl.signal)
      .then((d) => { data = d; loadError = ""; })
      .catch((e) => { if (e.name !== "AbortError") loadError = e.message; })
      .finally(() => { loading = false; });
    return () => ctrl.abort();
  });

  $effect(() => {
    get<Plan[]>("/api/platform/plans").then((p) => (plans = p)).catch(toastError);
  });

  const KINDS: Record<string, string> = { diagnostic: "Diagnostic centre", opd: "OPD", clinic: "Clinic" };
  const host = location.host.replace(/^[^.]+\./, "");

  // ---------- add / edit a client ----------
  let dialogOpen = $state(false);
  let editing = $state<Client | null>(null);
  let slugEdited = false;
  let shownPassword = $state<{ password: string; slug: string; name: string } | null>(null);
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
    name: text("Enter the centre's name.", 200, 2),
    slug: z.string().trim(),
    kind: z.enum(["diagnostic", "opd", "clinic"]),
    plan_id: z.string(),
    owner_name: z.string().trim(),
    owner_email: z.string().trim(),
    owner_temporary_password: z.string(),
  });
  const labels = { name: "Centre name", slug: "Address", kind: "Type", plan_id: "Plan", owner_name: "Owner's name",
                   owner_email: "Owner's email", owner_temporary_password: "Temporary password" };
  type Values = z.input<typeof schema>;
  const blank = (): Values => ({ name: "", slug: "", kind: "diagnostic", plan_id: plans[0]?.id ?? "", owner_name: "", owner_email: "",
                                 owner_temporary_password: `Welcome-${crypto.getRandomValues(new Uint32Array(1))[0] % 90000 + 10000}` });

  const form = new Form({
    schema, initial: blank(),
    rules: (v, add) => {
      if (editing) return;
      if (!/^[a-z][a-z0-9-]{1,38}[a-z0-9]$/.test(v.slug.trim()))
        add("slug", "Use 3 to 40 lower-case letters, numbers and dashes, starting with a letter.");
      if (v.owner_name.trim().length < 2) add("owner_name", "Enter the owner's name.");
      const e = email("Enter the owner's email.").safeParse(v.owner_email);
      if (!e.success) add("owner_email", e.error.issues[0].message);
      if (!v.owner_temporary_password.trim()) add("owner_temporary_password", "Enter a temporary password.");
    },
    onSubmit: async (v) => {
      if (editing) {
        await patch(`/api/platform/clients/${editing.id}`, { name: v.name, kind: v.kind, plan_id: v.plan_id || null });
        notify(`${v.name} saved.`);
      } else {
        const c = await post<Client>("/api/platform/clients", { ...v, plan_id: v.plan_id || null });
        pwCopied = false;
        shownPassword = { password: v.owner_temporary_password, slug: c.slug, name: c.name };
      }
      dialogOpen = false;
      reload++;
    },
  });

  function openAdd() {
    editing = null;
    slugEdited = false;
    form.reset(blank());
    dialogOpen = true;
  }

  function openEdit(c: Client) {
    editing = c;
    form.reset({ ...blank(), name: c.name, slug: c.slug, kind: c.kind, plan_id: c.plan?.id ?? "" });
    dialogOpen = true;
  }

  function suggestSlug() {
    if (!editing && !slugEdited) form.values.slug = form.values.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);
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

  function actionsFor(c: Client): RowAction[] {
    return [
      { label: "Open their workspace", icon: "arrowRight", href: `${location.protocol}//${c.slug}.${host}/`, newTab: true },
      ...(canManage ? [
        { label: "Edit", icon: "edit", onclick: () => openEdit(c), hint: "Name, type and plan" },
        c.status === "active"
          ? { label: "Suspend", icon: "lock", tone: "danger" as const, onclick: () => setStatus(c, "suspended"), hint: "Signs everyone there out" }
          : { label: "Reactivate", icon: "check", onclick: () => setStatus(c, "active") },
      ] : []),
      ...(canBackups ? [{ label: "Backups", icon: "download", onclick: () => { backupsOf = c; backupsOpen = true; },
                          hint: "Their own copies: download or restore" }] : []),
    ];
  }
</script>

{#snippet clientCell(c: Client)}<div class="cell-title">{c.name}</div><div class="cell-sub mono">{c.slug}.{host}</div>{/snippet}
{#snippet statusCell(c: Client)}
  <StatusBadge tone={c.status === "active" ? "success" : "destructive"} label={c.status === "active" ? "Active" : "Suspended"}
               help={c.status === "active" ? "" : "Nobody there can sign in."} />
{/snippet}

<PageHeader eyebrow="Clients" title="Clients" description="Every centre on CIDMS: its address, plan and whether it's active.">
  {#snippet actions()}{#if canManage}<Button variant="primary" icon="plus" onclick={openAdd}>Add a client</Button>{/if}{/snippet}
</PageHeader>

<section class="card" aria-label="Clients">
  <FilterBar placeholder="Search by name or address…" searchLabel="Search clients" inlineKeys={["status"]}>
    {#snippet inline()}
      <label class="sr-only" for="status">Status</label>
      <select id="status" class="select" value={status} onchange={(e) => setQuery({ status: e.currentTarget.value, page: null })}>
        <option value="">Any status</option><option value="active">Active</option><option value="suspended">Suspended</option>
      </select>
    {/snippet}
  </FilterBar>
  <DataTable label="Clients" rows={data?.items ?? []} {loading} error={loadError} onretry={() => reload++} page={data}
             actions={actionsFor} actionsLabel={(c) => `Actions for ${c.name}`} onrowclick={canManage ? openEdit : undefined}
             empty={{ icon: "building", title: search || status ? "No client matches." : "No clients yet." }}
             columns={[
               { key: "client", label: "Client", cell: clientCell, mobile: "title" },
               { key: "kind", label: "Type", value: (c) => KINDS[c.kind] ?? c.kind, mobile: "sub" },
               { key: "plan", label: "Plan", value: (c) => (c.plan ? `${c.plan.name} · ${rupees(c.plan.price_monthly)}/month` : "—") },
               { key: "paid", label: "Paid until", value: (c) => date(c.paid_until), nowrap: true, tip: "The last day the subscription is paid for." },
               { key: "status", label: "Status", cell: statusCell, mobile: "end" },
             ]} />
</section>

<FormDialog bind:open={dialogOpen} title={editing ? `Edit ${editing.name}` : "Add a client"} icon={editing ? "edit" : "building"} tone="info" wide
        description={editing ? "The address can't be changed: staff and printed QR codes use it." : "The owner gets a temporary password and chooses their own at first sign-in."}
            submitLabel={editing ? "Save changes" : "Add client"} busy={form.submitting} busyLabel={editing ? "Saving…" : "Adding…"}
            onsubmit={submitting(form, "Couldn't save")}>
    <FormErrors {form} {labels} idPrefix="c_" />
    <div class="form-grid">
      <Field id="c_name" label="Centre name" required error={form.error("name")} tip="As it appears on bills, reports and the sign-in page.">
        {#snippet children({ invalid, describedby })}<input id="c_name" class="input" autocomplete="off" bind:value={form.values.name} {...form.field("name")}
                 oninput={() => { suggestSlug(); form.field("name").oninput(); }} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
      </Field>
      <Field id="c_slug" label="Address" required={!editing} error={form.error("slug")} hint="{form.values.slug || 'name'}.{host}"
             tip="The centre's own web address. Lower-case letters, numbers and dashes. It can't be changed later, so choose carefully.">
        {#snippet children({ invalid, describedby })}<input id="c_slug" class="input mono" autocomplete="off" bind:value={form.values.slug} disabled={!!editing}
                 {...form.field("slug")} oninput={() => { slugEdited = true; form.field("slug").oninput(); }} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
      </Field>
      <Field id="c_kind" label="Type" error={form.error("kind")} tip="Sets which features are switched on. A diagnostic centre gets the worklist and imaging.">
        {#snippet children({ invalid, describedby })}
          <select id="c_kind" class="select" bind:value={form.values.kind} {...form.field("kind")} aria-invalid={invalid} aria-describedby={describedby}>
            {#each Object.entries(KINDS) as [v, l] (v)}<option value={v}>{l}</option>{/each}
          </select>
        {/snippet}
      </Field>
      <Field id="c_plan_id" label="Plan" error={form.error("plan_id")} tip="The plan sets the monthly price and limits (staff accounts, bills a month, storage). It can be changed at any time.">
        {#snippet children({ invalid, describedby })}
          <select id="c_plan_id" class="select" bind:value={form.values.plan_id} {...form.field("plan_id")} aria-invalid={invalid} aria-describedby={describedby}>
            <option value="">No plan yet</option>
            {#each plans as p (p.id)}<option value={p.id}>{p.name} · {rupees(p.price_monthly)}/month · {p.max_users} staff</option>{/each}
          </select>
        {/snippet}
      </Field>
    </div>
    {#if !editing}
      <h3 class="form-section-title"><Icon name="user" /> Owner</h3>
      <div class="form-grid">
        <Field id="c_owner_name" label="Owner's name" required error={form.error("owner_name")}>
          {#snippet children({ invalid, describedby })}<input id="c_owner_name" class="input" autocomplete="off" bind:value={form.values.owner_name} {...form.field("owner_name")} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
        </Field>
        <Field id="c_owner_email" label="Owner's email" required error={form.error("owner_email")} tip="The owner signs in with this email. They can add the rest of their staff themselves.">
          {#snippet children({ invalid, describedby })}<input id="c_owner_email" class="input" type="email" autocomplete="off" bind:value={form.values.owner_email} {...form.field("owner_email")} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
        </Field>
        <div class="full">
          <Field id="c_owner_temporary_password" label="Temporary password" required error={form.error("owner_temporary_password")} hint="They choose their own at first sign-in.">
            {#snippet children({ invalid, describedby })}<input id="c_owner_temporary_password" class="input mono" bind:value={form.values.owner_temporary_password} {...form.field("owner_temporary_password")} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
          </Field>
        </div>
      </div>
    {/if}
</FormDialog>

<Dialog open={!!shownPassword} onclose={() => (shownPassword = null)} title="Centre added" icon="check" tone="success"
        description={shownPassword ? `The owner signs in at ${shownPassword.slug}.${host} with this temporary password. Copy it now and give it to them.` : ""}>
  {#if shownPassword}
    <div class="stack-sm">
      <div class="alert alert-warning" role="alert"><Icon name="alert" /><div>This password won't be shown again. They choose their own the first time they sign in.</div></div>
      <div class="code-box">
        <pre class="mono" aria-label="Temporary password">{shownPassword.password}</pre>
        <button type="button" class="btn btn-outline btn-icon btn-sm" aria-label="Copy the password" use:tooltip={pwCopied ? "Copied" : "Copy the password"}
                onclick={copyPassword}><Icon name={pwCopied ? "check" : "clipboard"} size="sm" /></button>
      </div>
    </div>
  {/if}
  {#snippet footer()}<Button variant="primary" onclick={() => (shownPassword = null)}>{pwCopied ? "Done" : "I've saved it"}</Button>{/snippet}
</Dialog>

<Dialog bind:open={backupsOpen} title={backupsOf ? `Backups · ${backupsOf.name}` : "Backups"} icon="download" tone="info" wide
        onclose={() => (backupsOf = null)}>
  {#if backupsOf}
    <div class="stack-lg"><ClientBackupsPanel base="/api/platform/clients/{backupsOf.id}/backups" schedule={false} who={backupsOf.name} /></div>
  {/if}
</Dialog>
