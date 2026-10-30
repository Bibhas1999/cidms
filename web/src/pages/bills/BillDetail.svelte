<script lang="ts">
  import { connection } from "../../lib/connection.svelte";
  import { outbox } from "../../lib/outbox.svelte";
  import { FEATURES } from "../../lib/features";
  import FormDialog from "../../components/FormDialog.svelte";
  import EditTestsDialog from "../../components/EditTestsDialog.svelte";
  import Field from "../../components/Field.svelte";
  import Icon from "../../components/Icon.svelte";
  import { ApiError, get, newRequestKey, post } from "../../lib/api";
  import { BILL_STATUS, LINE_STATUS, PAYMENT_MODES, modeLabel, paymentState, type Bill, type PaymentMode } from "../../lib/bill-types";
  import { date, dateTime, rupees } from "../../lib/format";
  import { session } from "../../lib/session.svelte";
  import { notify, notifyError } from "../../lib/toast.svelte";
  import { tooltip } from "../../lib/tooltip";

  let { params }: { params: Record<string, string> } = $props();

  let bill = $state<Bill | null>(null);
  let loadError = $state("");

  async function load() {
    try {
      bill = await get<Bill>(`/api/bills/${params.id}`);
      loadError = "";
    } catch (e) {
      loadError = (e as Error).message;
    }
  }
  $effect(() => { params.id; load(); });

  // Opened from a list's row buttons: /bills/<id>?collect=1 or ?edit=1 opens that dialog straight away.
  let autoOpened = false;
  $effect(() => {
    if (!bill || autoOpened) return;
    autoOpened = true;
    const q = new URLSearchParams(location.search);
    if (q.get("collect") && Number(bill.due) > 0 && bill.status !== "cancelled" && session.can("payments.collect")) openPay();
    else if (q.get("edit") && bill.status === "on_hold" && Number(bill.due) > 0 && session.can("billing.edit")) editOpen = true;
  });

  const live = $derived(bill?.status !== "cancelled");
  const due = $derived(Number(bill?.due ?? 0));
  const paid = $derived(Number(bill?.paid ?? 0));
  // A bill with money due is put on hold before any change; a fully paid bill can't be held or changed.
  const fullyPaid = $derived(!!bill && Number(bill.total) > 0 && due <= 0);
  const editable = $derived(live && bill?.status === "on_hold" && !fullyPaid);
  const pay = $derived(bill ? paymentState(bill) : null);

  // ---------- collect a payment / refund ----------
  let payOpen = $state(false);
  let refundOpen = $state(false);
  let amount = $state("");
  let mode = $state<PaymentMode>("cash");
  let reference = $state("");
  let note = $state("");
  let errors = $state<Record<string, string>>({});
  let busy = $state(false);
  let requestKey = "";
  // Checked as the amount is typed: more than is due (a payment) or than has been paid (a refund) shows an error at
  // once and the button stays off until it's put right.
  function amountProblem(limit: number, words: string): string {
    if (amount === "" || amount === null) return "";
    const n = Number(amount);
    if (!Number.isFinite(n) || n <= 0) return "Enter an amount above ₹0.";
    if (Math.abs(Math.round(n * 100) - n * 100) > 1e-6) return "Use at most two decimal places (paise).";
    if (Math.round(n * 100) > Math.round(limit * 100)) return `Can't be more than ${words}, ${rupees(limit)}.`;
    return "";
  }
  const payProblem = $derived(amountProblem(due, "what's due"));
  const refundProblem = $derived(amountProblem(paid, "what's been paid"));

  function openPay() {
    amount = due.toFixed(2); mode = "cash"; reference = ""; note = ""; errors = {}; requestKey = newRequestKey(); payOpen = true;
  }
  function openRefund() {
    amount = ""; mode = "cash"; note = ""; errors = {}; requestKey = newRequestKey(); refundOpen = true;
  }

  async function submitMoney(kind: "payments" | "refunds") {
    if (kind === "payments" ? payProblem : refundProblem) { document.getElementById(kind === "payments" ? "pay-amount" : "ref-amount")?.focus(); return; }
    busy = true; errors = {};
    try {
      const body = kind === "payments" ? { mode, amount, reference, note } : { mode, amount, note };
      if (kind === "payments" && !connection.usable && (await keepPaymentOffline(body))) return;
      bill = await post<Bill>(`/api/bills/${bill!.id}/${kind}`, body, { "Idempotency-Key": requestKey });
      payOpen = refundOpen = false;
      notify(kind === "payments" ? `${rupees(amount)} received.${due - Number(amount) <= 0 ? " The bill is fully paid." : ""}` : `${rupees(amount)} refunded.`,
             { title: kind === "payments" ? "Payment saved" : "Refund saved" });
    } catch (e) {
      if (kind === "payments" && e instanceof ApiError && e.transient && (await keepPaymentOffline({ mode, amount, reference, note }))) return;
      if (e instanceof ApiError && Object.keys(e.fieldErrors).length) errors = e.fieldErrors;
      else notifyError(e, { title: kind === "payments" ? "Couldn't save the payment" : "Couldn't save the refund" });
    } finally {
      busy = false;
    }
  }

  /** CIDMS can't be reached: keep the payment on this computer and send it when the connection is back. */
  async function keepPaymentOffline(body: Record<string, unknown>): Promise<boolean> {
    const b = bill!;
    const kept = await outbox.add(requestKey, { method: "POST", path: `/api/bills/${b.id}/payments`, body },
                                  `${rupees(String(body.amount))} from ${b.patient_name} on ${b.invoice_no}`, `/bills/${b.id}`);
    if (!kept) return false;
    payOpen = false;
    notify(`${rupees(String(body.amount))} is kept on this computer and goes to CIDMS when the connection is back.`,
           { kind: "info", title: "Payment saved offline", duration: 0 });
    return true;
  }

  let editOpen = $state(false);

  // ---------- hold / confirm / cancel ----------
  let reasonOpen = $state<"" | "hold" | "cancel">("");
  let reason = $state("");

  async function setStatus(action: "hold" | "cancel" | "confirm") {
    busy = true; errors = {};
    try {
      bill = await post<Bill>(`/api/bills/${bill!.id}/${action}`, action === "confirm" ? {} : { reason });
      reasonOpen = "";
      notify({ hold: "The bill is on hold.", cancel: "The bill is cancelled.", confirm: "The bill is confirmed." }[action]);
    } catch (e) {
      if (e instanceof ApiError && e.field === "reason") errors = { reason: e.message };
      else notifyError(e, { title: "Couldn't change the bill" });
    } finally {
      busy = false;
    }
  }

  // Reports: doctors write them; everyone can open a signed one (to print it for the patient).
  const canReport = $derived(session.can("reports.write") || session.can("reports.sign"));

  // Each test's report: Pending -> Ready -> Delivered, set here on the bill (one test, or all at once).
  const canProgress = $derived(session.can("reports.deliver") || session.can("worklist.update"));
  const liveLines = $derived(bill?.items.filter((l) => l.status !== "cancelled") ?? []);
  const notAll = (status: string) => liveLines.some((l) => l.status !== status);
  let progressBusy = $state(false);

  async function setLine(line: { id: string; test_name: string }, status: string) {
    if (progressBusy) return;
    progressBusy = true;
    try {
      await post(`/api/worklist/${line.id}/status`, { status });
      notify(`${line.test_name}: ${LINE_STATUS[status][1].toLowerCase()}.`, { kind: "success" });
      await load();
    } catch (e) { notifyError(e); await load(); } finally { progressBusy = false; }
  }

  async function setAll(status: "reported" | "delivered") {
    if (progressBusy || !bill) return;
    progressBusy = true;
    try {
      await post(`/api/bills/${bill.id}/tests/status`, { status });
      notify(status === "delivered" ? "All reports marked delivered." : "All reports marked ready.", { kind: "success" });
      await load();
    } catch (e) { notifyError(e); } finally { progressBusy = false; }
  }

  const discountText = $derived(bill?.discount_type === "percent" ? `${Number(bill.discount_value)}%` : "");
</script>

{#if loadError}
  <div class="alert alert-destructive" role="alert"><Icon name="alert" /><div><div class="alert-title">Couldn't open this bill</div>{loadError}</div></div>
  <a class="btn btn-outline" href="/bills" style="align-self: flex-start">Back to bills</a>
{:else if !bill}
  <div class="card"><div class="empty" aria-busy="true">Loading…</div></div>
{:else}
  <div class="page-header">
    <div>
      <a class="link-button" href="/bills"><Icon name="chevronRight" size="sm" class="flip" /> All bills</a>
      <div class="meta-row" style="margin-top: 8px">
        <span class="eyebrow">Bill</span>
        {#if pay}<span class="badge {pay[0]}">{pay[1]}</span>{/if}
        {#if bill.status !== "confirmed"}<span class="badge {BILL_STATUS[bill.status][0]}">{BILL_STATUS[bill.status][1]}</span>{/if}
      </div>
      <h1 class="page-title mono" style="font-family: var(--font-heading)">{bill.invoice_no}</h1>
      <p class="page-description">{bill.patient_name} · {date(bill.bill_date)} · billed by {bill.created_by_name || "—"}{#if bill.legacy_no} · old bill #{bill.legacy_no}{/if}</p>
    </div>
    <div class="row-wrap">
      <a class="btn btn-outline" href="/bills/{bill.id}/print" target="_blank" rel="noopener"><Icon name="printer" /> Print</a>
      {#if live && due > 0 && session.can("payments.collect")}<button class="btn btn-primary" onclick={openPay}><Icon name="wallet" /> Collect {rupees(due)}</button>{/if}
    </div>
  </div>

  {#if !live}
    <div class="alert alert-destructive"><Icon name="alert" /><div><div class="alert-title">This bill is cancelled</div>{bill.cancel_reason}</div></div>
  {:else if bill.status === "on_hold"}
    <div class="alert alert-warning"><Icon name="clock" /><div><div class="alert-title">This bill is on hold</div>It isn't counted as confirmed until someone confirms it.</div></div>
  {/if}

  <div class="grid-3 items-start">
    <div class="span-2 stack">
      <section class="card" aria-labelledby="tests-title">
        <div class="card-header"><div><h2 class="card-title" id="tests-title">Tests</h2>
          <p class="card-description">Each test's report: pending, ready to collect, or delivered to the patient.</p></div>
          <div class="row-wrap tests-actions">
            {#if live && canProgress && liveLines.length > 1}
              {#if notAll("reported") && notAll("delivered")}<button class="btn btn-outline btn-sm" disabled={progressBusy} onclick={() => setAll("reported")}><Icon name="check" size="sm" /> All ready</button>{/if}
              {#if notAll("delivered")}<button class="btn btn-outline btn-sm" disabled={progressBusy} onclick={() => setAll("delivered")}><Icon name="inbox" size="sm" /> All delivered</button>{/if}
            {/if}
            {#if live && session.can("billing.edit")}
              <span use:tooltip={editable ? "" : fullyPaid ? "A fully paid bill can't be changed" : "Put the bill on hold first, then change it"}>
                <button class="btn btn-outline btn-sm" disabled={!editable} onclick={() => (editOpen = true)}><Icon name="plus" size="sm" /> Change tests</button>
              </span>
            {/if}
          </div>
        </div>
        <div class="card-flush">
          <div class="table-wrap"><table class="table" style="min-width: 0">
            <thead><tr><th>Test</th><th>Report</th><th class="num">Price</th><th class="num">Qty</th><th class="num">Amount</th></tr></thead>
            <tbody>
              {#each bill.items as line (line.id)}
                <tr style={line.status === "cancelled" ? "opacity: .55" : ""}>
                  <td><div class="cell-title" style={line.status === "cancelled" ? "text-decoration: line-through" : ""}>{line.test_name}</div>
                    <div class="cell-sub">{line.department_name || "—"}{#if line.accession_no} · <span class="mono">{line.accession_no}</span>{/if}</div>
                    {#if FEATURES.testReports && line.status !== "cancelled" && line.test_id && (canReport || line.status === "reported")}
                      <a class="link-button text-sm" href="/test-reports/{line.id}" aria-label="Report for {line.test_name}">
                        <Icon name="clipboard" size="sm" /> {canReport && line.status !== "reported" && line.status !== "delivered" ? "Write report" : "Report"}</a>
                    {/if}</td>
                  <td>
                    {#if live && canProgress && line.status !== "cancelled"}
                      <label class="sr-only" for="prog-{line.id}">Report for {line.test_name}</label>
                      <select id="prog-{line.id}" class="select select-sm progress-select is-{line.status}" value={line.status} disabled={progressBusy}
                              onchange={(e) => setLine(line, e.currentTarget.value)}>
                        <option value="billed">Pending</option>
                        {#if line.status === "scanned"}<option value="scanned">In progress</option>{/if}
                        <option value="reported">Ready</option>
                        <option value="delivered">Delivered</option>
                      </select>
                    {:else}<span class="badge {LINE_STATUS[line.status][0]}">{LINE_STATUS[line.status][1]}</span>{/if}
                  </td>
                  <td class="num money">{rupees(line.unit_price)}</td>
                  <td class="num tabular">{line.quantity}</td>
                  <td class="num money">{rupees(line.amount)}</td>
                </tr>
              {/each}
            </tbody>
          </table></div>
        </div>
        <div class="card-content">
          <dl class="totals">
            <div><dt>Subtotal</dt><dd class="money">{rupees(bill.subtotal)}</dd></div>
            {#if Number(bill.discount_amount) > 0}<div><dt>Discount {discountText}</dt><dd class="money">− {rupees(bill.discount_amount)}</dd></div>{/if}
            <div class="grand"><dt>Total</dt><dd class="money">{rupees(bill.total)}</dd></div>
            <div><dt>Paid</dt><dd class="money">{rupees(bill.paid)}</dd></div>
            <div class={due > 0 ? "is-due" : ""}><dt>Due</dt><dd class="money">{rupees(bill.due)}</dd></div>
          </dl>
        </div>
      </section>

      <section class="card" aria-labelledby="pay-title">
        <div class="card-header"><div><h2 class="card-title" id="pay-title">Payments</h2>
          <p class="card-description">Every amount received or given back. Nothing here is ever changed or removed.</p></div>
          {#if paid > 0 && session.can("payments.collect")}<button class="btn btn-ghost-destructive btn-sm" onclick={openRefund}>Refund</button>{/if}
        </div>
        <div class="card-flush">
          {#if bill.payments.length}
            <div class="table-wrap"><table class="table" style="min-width: 0">
              <thead><tr><th>When</th><th>How</th><th>Received by</th><th class="num">Amount</th></tr></thead>
              <tbody>
                {#each bill.payments as p (p.id)}
                  <tr>
                    <td class="text-sm nowrap">{dateTime(p.received_at)}</td>
                    <td><div class="row" style="gap: 8px">{#if p.kind === "refund"}<span class="badge badge-destructive badge-plain">Refund</span>{/if}<span>{modeLabel(p.mode)}</span></div>
                      {#if p.reference || p.note}<div class="cell-sub">{[p.reference, p.note].filter(Boolean).join(" · ")}</div>{/if}</td>
                    <td class="text-sm">{p.received_by_name || "—"}</td>
                    <td class="num money {p.kind === 'refund' ? 'money-due' : ''}">{p.kind === "refund" ? "− " : ""}{rupees(p.amount)}</td>
                  </tr>
                {/each}
              </tbody>
            </table></div>
          {:else}
            <div class="empty"><Icon name="wallet" />Nothing paid yet.</div>
          {/if}
        </div>
      </section>
    </div>

    <div class="stack">
      <section class="card" aria-labelledby="patient-title">
        <div class="card-header"><h2 class="card-title" id="patient-title">Patient</h2>
          <a class="btn btn-ghost btn-sm" href="/patients/{bill.patient_id}">Open</a></div>
        <div class="card-content">
          <dl class="dl" style="grid-template-columns: 1fr">
            <div><dt>Name</dt><dd class="font-semibold">{bill.patient_name}</dd></div>
            <div><dt>Age and gender</dt><dd>{[bill.patient_age, bill.patient_gender].filter(Boolean).join(" · ") || "—"}</dd></div>
            <div><dt>Mobile</dt><dd class="tabular">{bill.patient_mobile || "—"}</dd></div>
            {#if bill.guardian_name}<div><dt>Guardian (C/O)</dt><dd>{bill.guardian_name}</dd></div>{/if}
            {#if bill.patient_address}<div><dt>Address</dt><dd>{bill.patient_address}</dd></div>{/if}
          </dl>
        </div>
      </section>
      <section class="card" aria-labelledby="bill-title">
        <div class="card-header"><h2 class="card-title" id="bill-title">Bill</h2></div>
        <div class="card-content">
          <dl class="dl" style="grid-template-columns: 1fr">
            <div><dt>Referred by</dt><dd>{bill.referring_doctor_name || "Self"}</dd></div>
            <div><dt>Billed</dt><dd>{dateTime(bill.created_at)} by {bill.created_by_name || "—"}</dd></div>
            {#if bill.notes}<div><dt>Notes</dt><dd>{bill.notes}</dd></div>{/if}
          </dl>
        </div>
        {#if live && session.can("billing.edit")}
          <div class="card-footer card-footer-stack">
            {#if bill.status === "on_hold"}
              <button class="btn btn-outline btn-block" disabled={busy} onclick={() => setStatus("confirm")}><Icon name="check" /> Confirm bill</button>
            {:else if fullyPaid}
              <p class="text-sm text-muted locked-note"><Icon name="lock" size="sm" /> Fully paid: this bill can't be put on hold or changed.</p>
            {:else}
              <button class="btn btn-outline btn-block" onclick={() => { reason = ""; errors = {}; reasonOpen = "hold"; }}
                      use:tooltip={"Needed before changing the tests or the discount"}><Icon name="clock" /> Put on hold</button>
            {/if}
            <button class="btn btn-ghost-destructive btn-block" onclick={() => { reason = ""; errors = {}; reasonOpen = "cancel"; }}><Icon name="x" /> Cancel bill</button>
          </div>
        {/if}
      </section>
    </div>
  </div>

  <EditTestsDialog bind:open={editOpen} {bill} onsaved={(b) => (bill = b)} />

  <FormDialog bind:open={payOpen} title="Collect a payment" icon="wallet" tone="info" description="{rupees(due)} is due on {bill.invoice_no}."
              submitLabel={`Receive ${rupees(amount || 0)}`} submitIcon="check" {busy} disabled={!Number(amount) || !!payProblem}
              onsubmit={() => submitMoney("payments")}>
      <div class="grid-2">
        <Field id="pay-amount" label="Amount (₹)" required error={payProblem || errors.amount}>
          {#snippet children({ invalid, describedby })}<input id="pay-amount" class="input money" type="number" min="0.01" step="0.01" max={due} bind:value={amount} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
        </Field>
        <Field id="pay-mode" label="Paid by" required error={errors.mode}>
          {#snippet children()}<select id="pay-mode" class="select" bind:value={mode}>{#each PAYMENT_MODES as [v, l] (v)}<option value={v}>{l}</option>{/each}</select>{/snippet}
        </Field>
      </div>
      {#if mode !== "cash"}
        <Field id="pay-ref" label="Reference" hint="UPI transaction ID, card slip or bank reference." error={errors.reference}>
          {#snippet children({ invalid, describedby })}<input id="pay-ref" class="input mono" bind:value={reference} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
        </Field>
      {/if}
  </FormDialog>

  <FormDialog bind:open={refundOpen} title="Give money back" icon="alert" tone="destructive" description="{rupees(paid)} has been paid on this bill. A refund is recorded with its reason; nothing is deleted."
              submitLabel="Save refund" submitVariant="destructive" {busy} disabled={!Number(amount) || !!refundProblem || note.trim().length < 3}
              onsubmit={() => submitMoney("refunds")}>
      <div class="grid-2">
        <Field id="ref-amount" label="Amount (₹)" required error={refundProblem || errors.amount}>
          {#snippet children({ invalid, describedby })}<input id="ref-amount" class="input money" type="number" min="0.01" step="0.01" max={paid} bind:value={amount} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
        </Field>
        <Field id="ref-mode" label="Given back by" required>
          {#snippet children()}<select id="ref-mode" class="select" bind:value={mode}>{#each PAYMENT_MODES as [v, l] (v)}<option value={v}>{l}</option>{/each}</select>{/snippet}
        </Field>
      </div>
      <Field id="ref-note" label="Reason" required hint="At least 3 characters." error={errors.note}>
        {#snippet children({ invalid, describedby })}<textarea id="ref-note" class="textarea" style="min-height: 72px" bind:value={note} aria-invalid={invalid} aria-describedby={describedby}></textarea>{/snippet}
      </Field>
  </FormDialog>

  <FormDialog open={reasonOpen !== ""} onclose={() => (reasonOpen = "")} title={reasonOpen === "cancel" ? "Cancel this bill?" : "Put this bill on hold?"}
          icon={reasonOpen === "cancel" ? "x" : "clock"} tone={reasonOpen === "cancel" ? "destructive" : "info"}
          description={reasonOpen === "cancel" ? (paid > 0 ? `${rupees(paid)} has been paid. Refund it first, then cancel.` : "The bill stays on record, marked cancelled, with your reason.") : "It won't count as confirmed until someone confirms it."}
          submitLabel={reasonOpen === "cancel" ? "Cancel bill" : "Put on hold"} submitVariant={reasonOpen === "cancel" ? "destructive" : "primary"}
          cancelLabel="Keep it" oncancel={() => (reasonOpen = "")} {busy} disabled={reason.trim().length < 3 || (reasonOpen === "cancel" && paid > 0)}
          onsubmit={() => setStatus(reasonOpen as "hold" | "cancel")}>
      <Field id="reason" label="Reason" required hint="At least 3 characters." error={errors.reason}>
        {#snippet children({ invalid, describedby })}<textarea id="reason" class="textarea" style="min-height: 72px" bind:value={reason} aria-invalid={invalid} aria-describedby={describedby}></textarea>{/snippet}
      </Field>
  </FormDialog>
{/if}

<style src="./styles/BillDetail.css"></style>
