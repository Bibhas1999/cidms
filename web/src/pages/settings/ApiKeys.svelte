<script lang="ts">
  import { z } from "zod";
  import Button from "../../components/Button.svelte";
  import DataTable from "../../components/DataTable.svelte";
  import Dialog from "../../components/Dialog.svelte";
  import FormDialog from "../../components/FormDialog.svelte";
  import Field from "../../components/Field.svelte";
  import FormErrors from "../../components/FormErrors.svelte";
  import Icon from "../../components/Icon.svelte";
  import InfoTip from "../../components/InfoTip.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import type { RowAction } from "../../components/RowMenu.svelte";
  import { get, post } from "../../lib/api";
  import { confirmDialog } from "../../lib/confirm.svelte";
  import { todayISO } from "../../lib/dates";
  import { Form } from "../../lib/form.svelte";
  import { dateTime } from "../../lib/format";
  import { submitting, text } from "../../lib/schemas";
  import { notify, notifyError } from "../../lib/toast.svelte";
  import { tooltip } from "../../lib/tooltip";
  import type { Page } from "../../lib/types";

  // Settings → API & integrations: keys other systems (a hospital's HIS, a doctor's EMR, a PACS) use to read the
  // centre's medical data at /api/v1. Never financial data. The key itself is shown once, when it's made.
  let { embedded = false }: { embedded?: boolean; params?: Record<string, string> } = $props();

  interface ApiKey {
    id: string; name: string; prefix: string; scopes: string[]; allowed_ips: string[]; expires_at: string | null;
    created_by_name: string; created_at: string; last_used_at: string | null; last_used_ip: string | null;
    revoked_at: string | null; revoked_by_name: string; replaced_by: string | null;
    status: "active" | "rolling" | "revoked" | "expired";
  }
  interface Created { api_key: ApiKey; key: string }
  interface ApiCall { id: number; key_id: string | null; key_name: string; key_prefix: string; method: string; path: string;
                      status: number; duration_ms: number; ip_address: string | null; created_at: string }

  const SCOPES: { id: string; label: string; tip: string }[] = [
    { id: "patients:read", label: "Patients", tip: "Name, patient number, age, gender, mobile, email and address." },
    { id: "orders:read", label: "Ordered tests", tip: "Which tests each patient is booked for and how far they've got (billed, scanned, reported, delivered), accession numbers, the referring doctor and times. No amounts, discounts or payments." },
    { id: "reports:read", label: "Signed reports", tip: "Signed and amended reports: findings, impression, the signing doctor and when, and the report PDF. Drafts are never shared." },
    { id: "images:read", label: "Imaging studies", tip: "Each study's StudyInstanceUID, modality and number of series and images, for matching in a PACS." },
    { id: "tests:read", label: "Test catalogue", tip: "Test names, codes, departments and modality (X-ray, CT…). Prices are never included." },
    { id: "doctors:read", label: "Referring doctors", tip: "Doctors' names and qualifications. No commissions or other money." },
  ];
  const scopeLabel = (id: string) => SCOPES.find((s) => s.id === id)?.label ?? id;
  const scopeTip = (id: string) => `${id}: ${SCOPES.find((s) => s.id === id)?.tip ?? ""}`;

  // ---------- the keys ----------
  let keys = $state<ApiKey[] | null>(null);
  let loadError = $state("");
  let reload = $state(0);

  $effect(() => {
    reload;
    const ctrl = new AbortController();
    get<ApiKey[]>("/api/integrations/keys", undefined, ctrl.signal)
      .then((k) => { keys = k; loadError = ""; })
      .catch((e) => { if (e.name !== "AbortError") loadError = e.message; });
    return () => ctrl.abort();
  });

  // ---------- creating one ----------
  const IP = /^(\d{1,3}(\.\d{1,3}){3}(\/\d{1,2})?|[0-9a-fA-F:]+(\/\d{1,3})?)$/;
  const splitIps = (v: string) => v.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);
  const schema = z.object({
    name: text("Give the key a name, such as the system that will use it.", 100),
    scopes: z.array(z.string()).min(1, "Choose at least one kind of data the key may read."),
    expires_on: z.string().refine((v) => !v || v >= todayISO(), "Pick a date from today on, or leave it empty."),
    allowed_ips: z.string().max(2000).refine((v) => splitIps(v).every((ip) => IP.test(ip)),
                                             "Use IP addresses or ranges like 203.0.113.7 or 203.0.113.0/24, one per line."),
  });
  const labels = { name: "Name", scopes: "What it may read", expires_on: "Expires on", allowed_ips: "Allowed IP addresses" };

  let createOpen = $state(false);
  let shown = $state<{ key: string; name: string; rolled: boolean } | null>(null);
  let copied = $state(false);

  const form = new Form({
    schema, initial: { name: "", scopes: ["patients:read", "orders:read", "reports:read"], expires_on: "", allowed_ips: "" },
    onSubmit: async (v) => {
      const r = await post<Created>("/api/integrations/keys", {
        name: v.name, scopes: v.scopes, expires_on: v.expires_on || null, allowed_ips: splitIps(v.allowed_ips),
      });
      createOpen = false;
      show(r, false);
      reload++;
    },
  });

  function openCreate() {
    form.reset();
    createOpen = true;
  }

  function toggleScope(id: string, on: boolean) {
    form.values.scopes = on ? [...form.values.scopes, id] : form.values.scopes.filter((s: string) => s !== id);
    form.touched.scopes = true;
    form.validate();
  }

  function show(r: Created, rolled: boolean) {
    copied = false;
    shown = { key: r.key, name: r.api_key.name, rolled };
  }

  async function copy(value: string, what = "Key") {
    try {
      await navigator.clipboard.writeText(value);
      copied = true;
      notify(`${what} copied.`);
    } catch {
      notify("Couldn't copy. Select the text and copy it yourself.", { kind: "warning" });
    }
  }

  // ---------- rolling and revoking ----------
  let rolling = $state<ApiKey | null>(null);
  let graceHours = $state(0);
  let rollBusy = $state(false);

  async function roll() {
    if (!rolling) return;
    rollBusy = true;
    try {
      const r = await post<Created>(`/api/integrations/keys/${rolling.id}/roll`, { grace_hours: graceHours });
      rolling = null;
      show(r, true);
      reload++;
    } catch (e) {
      notifyError(e, { title: "Couldn't roll the key" });
    } finally {
      rollBusy = false;
    }
  }

  async function revoke(k: ApiKey) {
    if (!(await confirmDialog({ title: `Revoke ${k.name}?`, confirmLabel: "Revoke key", tone: "danger",
                                message: `Anything using ${k.prefix}… stops working straight away. This can't be undone.` }))) return;
    try {
      await post(`/api/integrations/keys/${k.id}/revoke`);
      notify(`${k.name} revoked.`);
      reload++;
      if (usageKey?.id === k.id) usageReload++;
    } catch (e) {
      notifyError(e, { title: "Couldn't revoke the key" });
    }
  }

  function actionsFor(k: ApiKey): RowAction[] {
    const working = k.status === "active";
    return [
      { label: "View usage", icon: "activity", onclick: () => { usageKey = k; usagePage = 1; } },
      { label: "Roll", icon: "refresh", disabled: !working, onclick: () => { rolling = k; graceHours = 0; },
        hint: working ? "A new key with the same settings; the old one stops now or after a grace period" : "Only a working key can be rolled" },
      { label: "Revoke", icon: "x", tone: "danger", disabled: k.status === "revoked",
        onclick: () => revoke(k), hint: k.status === "revoked" ? "Already revoked" : "Stops the key straight away" },
    ];
  }

  // ---------- usage ----------
  let usageKey = $state<ApiKey | null>(null);
  let usagePage = $state(1);
  const USAGE_SIZE = 25;
  let usage = $state<Page<ApiCall> | null>(null);
  let usageError = $state("");
  let usageLoading = $state(false);
  let usageReload = $state(0);

  $effect(() => {
    usageReload;
    const ctrl = new AbortController();
    usageLoading = true;
    get<Page<ApiCall>>("/api/integrations/usage", { key_id: usageKey?.id, page: usagePage, size: USAGE_SIZE }, ctrl.signal)
      .then((d) => { usage = d; usageError = ""; })
      .catch((e) => { if (e.name !== "AbortError") usageError = e.message; })
      .finally(() => { usageLoading = false; });
    return () => ctrl.abort();
  });

  // ---------- quick start ----------
  const origin = typeof location !== "undefined" ? location.origin : "";
  const curl = $derived(`curl -H "Authorization: Bearer sdms_live_…" \\\n  "${origin}/api/v1/orders?from=${todayISO()}&limit=50"`);
</script>

{#snippet keyCell(k: ApiKey)}
  <div class="cell-title">{k.name}</div>
  <div class="cell-sub mono">{k.prefix}…</div>
{/snippet}

{#snippet scopesCell(k: ApiKey)}
  <div class="row-wrap" style="gap:6px">
    {#each k.scopes as s (s)}<span class="badge badge-navy badge-plain" use:tooltip={scopeTip(s)}>{scopeLabel(s)}</span>{/each}
  </div>
{/snippet}

{#snippet createdCell(k: ApiKey)}
  <div>{k.created_by_name || "—"}</div>
  <div class="cell-sub">{dateTime(k.created_at)}</div>
{/snippet}

{#snippet usedCell(k: ApiKey)}
  {#if k.last_used_at}
    <span use:tooltip={`Last used ${dateTime(k.last_used_at)}${k.last_used_ip ? ` from ${k.last_used_ip}` : ""}`}>{dateTime(k.last_used_at)}</span>
  {:else}<span class="text-muted">Never</span>{/if}
{/snippet}

{#snippet expiryCell(k: ApiKey)}
  {#if k.expires_at}<span use:tooltip={`Stops working at ${dateTime(k.expires_at)}`}>{dateTime(k.expires_at)}</span>
  {:else}<span class="text-muted">Never</span>{/if}
{/snippet}

{#snippet statusCell(k: ApiKey)}
  {#if k.status === "active"}
    <span class="badge badge-success" use:tooltip={k.allowed_ips.length ? `Works only from ${k.allowed_ips.join(", ")}` : "Works from any IP address"}>Active</span>
  {:else if k.status === "rolling"}
    <span class="badge badge-warning" use:tooltip={`Replaced by a new key; this one stops at ${dateTime(k.revoked_at)}`}>Being replaced</span>
  {:else if k.status === "expired"}
    <span class="badge badge-destructive" use:tooltip={`Expired ${dateTime(k.expires_at)}`}>Expired</span>
  {:else}
    <span class="badge badge-destructive" use:tooltip={`Revoked ${dateTime(k.revoked_at)}${k.revoked_by_name ? ` by ${k.revoked_by_name}` : ""}`}>Revoked</span>
  {/if}
{/snippet}

{#snippet callStatus(c: ApiCall)}
  <span class="badge {c.status < 300 ? 'badge-success' : c.status === 429 ? 'badge-warning' : 'badge-destructive'} tabular"
        use:tooltip={`${c.status} in ${c.duration_ms} ms`}>{c.status}</span>
{/snippet}

<PageHeader compact={embedded} eyebrow="Settings" title="API & integrations"
            tip="Other systems read the centre's medical data with an API key. Financial data (bills, prices, payments, dues) is never available through the API."
            description="Keys that let other systems, such as a hospital's HIS or a doctor's EMR, read patients, ordered tests, signed reports and images.">
  {#snippet actions()}<Button variant="primary" icon="plus" onclick={openCreate}>Create API key</Button>{/snippet}
</PageHeader>

<div class="alert alert-info" role="note">
  <Icon name="lock" />
  <div>Financial data (bills, prices, payments, dues) is never available through the API, whatever a key is allowed to read.</div>
</div>

<section class="card" aria-label="API keys">
  <DataTable label="API keys" rows={keys ?? []} loading={keys === null && !loadError} error={loadError} onretry={() => reload++}
             actions={actionsFor} actionsLabel={(k) => `Actions for ${k.name}`}
             empty={{ icon: "lock", title: "No API keys yet.", text: "Create one for each system that needs the centre's data." }}
             columns={[
               { key: "name", label: "Key", cell: keyCell, mobile: "title" },
               { key: "scopes", label: "May read", cell: scopesCell },
               { key: "created", label: "Created", cell: createdCell, optional: true },
               { key: "used", label: "Last used", cell: usedCell, nowrap: true },
               { key: "expires", label: "Expires", cell: expiryCell, nowrap: true, optional: true },
               { key: "status", label: "Status", cell: statusCell, mobile: "end" },
             ]} />
</section>

<section class="card" aria-labelledby="usage-title">
  <div class="card-header">
    <div>
      <h3 class="card-title" id="usage-title">Recent requests{usageKey ? ` · ${usageKey.name}` : ""}
        <InfoTip about="recent requests" text="Every call to the API: when, what was asked for, the answer's status and where it came from. Kept for 30 days. What was sent and returned is never stored." /></h3>
      <p class="text-sm text-muted">{usageKey ? `Calls made with ${usageKey.prefix}…` : "Calls made with any of the centre's keys."}</p>
    </div>
    {#if usageKey}<Button size="sm" icon="x" onclick={() => { usageKey = null; usagePage = 1; }}>Show all keys</Button>{/if}
  </div>
  <DataTable label="Recent API requests" rows={usage?.items ?? []} loading={usageLoading && !usage} error={usageError}
             onretry={() => usageReload++} page={usage} onpage={(p) => (usagePage = p)}
             rowKey={(c) => String(c.id)}
             empty={{ icon: "activity", title: "No requests yet.", text: "Calls appear here as soon as a key is used." }}
             columns={[
               { key: "time", label: "Time", value: (c) => dateTime(c.created_at), nowrap: true, mobile: "title" },
               { key: "req", label: "Request", value: (c) => `${c.method} ${c.path}`, class: "mono", mobile: "sub" },
               { key: "status", label: "Status", cell: callStatus, mobile: "end" },
               { key: "key", label: "Key", value: (c) => c.key_name ? `${c.key_name} (${c.key_prefix}…)` : "No valid key", optional: true },
               { key: "ip", label: "IP address", value: (c) => c.ip_address ?? "—", class: "tabular", optional: true },
             ]} />
</section>

<section class="card" aria-labelledby="qs-title">
  <div class="card-header"><h3 class="card-title" id="qs-title">Quick start</h3></div>
  <div class="card-content stack-sm">
    <p class="text-sm">Send the key on every request in the <span class="kbd">Authorization</span> header. Lists come back as
      <span class="mono">{"{ data, next_cursor }"}</span>; pass <span class="mono">next_cursor</span> back as <span class="mono">?cursor=</span> for the next page.</p>
    <div class="code-box">
      <pre class="mono">{curl}</pre>
      <button type="button" class="btn btn-ghost btn-icon btn-sm" aria-label="Copy the example" use:tooltip={"Copy the example"}
              onclick={() => copy(curl.replace("\\\n  ", ""), "Example")}><Icon name="clipboard" size="sm" /></button>
    </div>
    <p class="text-sm"><a href="/api/v1/docs" target="_blank" rel="noopener">Open the API documentation <Icon name="arrowRight" size="sm" /></a>
      <span class="text-muted">· every endpoint, its filters and what it returns. Up to 600 requests a minute per key.</span></p>
  </div>
</section>

<FormDialog bind:open={createOpen} title="Create API key" icon="lock" tone="info" wide
        description="Make a separate key for each system, so you can see and stop each one on its own."
            submitLabel="Create key" busy={form.submitting} busyLabel="Creating…" onsubmit={submitting(form, "Couldn't create the key")}>
    <FormErrors {form} {labels} idPrefix="k_" />
    <Field id="k_name" label="Name" required error={form.error("name")}
           tip="Which system will use it, e.g. City Hospital HIS. Shown in the key list and the request log.">
      {#snippet children({ invalid, describedby })}
        <input id="k_name" class="input" autocomplete="off" bind:value={form.values.name} {...form.field("name")} aria-invalid={invalid} aria-describedby={describedby} />
      {/snippet}
    </Field>

    <fieldset class="field" style="border:0; padding:0; margin:0" aria-describedby="k_scopes-note">
      <legend class="label" style="margin-bottom: 6px">What it may read<span class="req" aria-hidden="true">*</span></legend>
      <span id="k_scopes"></span>
      {#each SCOPES as s (s.id)}
        <div class="check-row check-top">
          <input id="k_scope_{s.id}" class="checkbox" type="checkbox" checked={form.values.scopes.includes(s.id)}
                 onchange={(e) => toggleScope(s.id, e.currentTarget.checked)} />
          <label for="k_scope_{s.id}"><span class="font-semibold">{s.label}</span> <span class="text-muted mono">{s.id}</span></label>
          <InfoTip text={s.tip} about={s.label} />
        </div>
      {/each}
      <p id="k_scopes-note" class="hint"><Icon name="lock" size="sm" /> Financial data (bills, prices, payments, dues) is never available through the API.</p>
      {#if form.error("scopes")}<p class="field-error"><Icon name="alert" size="sm" />{form.error("scopes")}</p>{/if}
    </fieldset>

    <div class="form-grid">
      <Field id="k_expires_on" label="Expires on" optional error={form.error("expires_on")}
             tip="The key stops working at the end of this day (India time). Leave empty for a key that works until it's revoked.">
        {#snippet children({ invalid, describedby })}
          <input id="k_expires_on" class="input" type="date" min={todayISO()} bind:value={form.values.expires_on} {...form.field("expires_on")}
                 aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
      <Field id="k_allowed_ips" label="Allowed IP addresses" optional error={form.error("allowed_ips")}
             hint="One per line. Leave empty to allow any address."
             tip="Only calls from these addresses are accepted: single addresses (203.0.113.7) or ranges (203.0.113.0/24). Ask the other system's supplier for their server's address.">
        {#snippet children({ invalid, describedby })}
          <textarea id="k_allowed_ips" class="input textarea mono" rows="3" placeholder="203.0.113.7" bind:value={form.values.allowed_ips}
                    {...form.field("allowed_ips")} aria-invalid={invalid} aria-describedby={describedby}></textarea>
        {/snippet}
      </Field>
    </div>
</FormDialog>

<Dialog open={!!shown} onclose={() => (shown = null)} title={shown?.rolled ? "Your new key" : "Your API key"} icon="check" tone="success"
        description={shown ? `For ${shown.name}. Copy it now and keep it somewhere safe.` : ""}>
  {#if shown}
    <div class="stack-sm">
      <div class="alert alert-warning" role="alert"><Icon name="alert" /><div>This key won't be shown again. If it's lost, roll or revoke it and make a new one.</div></div>
      <div class="code-box">
        <pre class="mono" aria-label="API key">{shown.key}</pre>
        <button type="button" class="btn btn-outline btn-icon btn-sm" aria-label="Copy the key" use:tooltip={copied ? "Copied" : "Copy the key"}
                onclick={() => copy(shown!.key)}><Icon name={copied ? "check" : "clipboard"} size="sm" /></button>
      </div>
    </div>
  {/if}
  {#snippet footer()}<Button variant="primary" onclick={() => (shown = null)}>{copied ? "Done" : "I've saved it"}</Button>{/snippet}
</Dialog>

<Dialog open={!!rolling} onclose={() => (rolling = null)} title={rolling ? `Roll ${rolling.name}?` : "Roll key"} icon="refresh" tone="info"
        description="You get a new key with the same name, permissions, addresses and expiry. The old key stops working when you choose.">
  <Field id="k_grace" label="Old key stops working"
         tip="A grace period lets the other system switch to the new key without a gap. Until then both keys work.">
    {#snippet children({ describedby })}
      <select id="k_grace" class="select" bind:value={graceHours} aria-describedby={describedby}>
        <option value={0}>Straight away</option>
        <option value={1}>In 1 hour</option>
        <option value={24}>In 24 hours</option>
        <option value={168}>In 7 days</option>
      </select>
    {/snippet}
  </Field>
  {#snippet footer()}
    <Button onclick={() => (rolling = null)}>Cancel</Button>
    <Button variant="primary" loading={rollBusy} loadingText="Rolling…" onclick={roll}>Roll key</Button>
  {/snippet}
</Dialog>

<style>
  .code-box { display: flex; align-items: flex-start; gap: 8px; background: var(--muted); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
  .code-box pre { margin: 0; flex: 1; min-width: 0; white-space: pre-wrap; word-break: break-all; }
  .check-row :global(.tip) { margin-left: auto; }
  .hint :global(.icon) { vertical-align: -2px; }
</style>
