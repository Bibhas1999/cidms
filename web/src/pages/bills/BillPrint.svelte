<script lang="ts">
  import { get } from "../../lib/api";
  import { modeLabel, type Bill } from "../../lib/bill-types";
  import { date, dateTime, rupees } from "../../lib/format";
  import { session } from "../../lib/session.svelte";
  import type { CentreSettings } from "../../lib/types";

  // The printed bill / receipt on the centre's letterhead (A5 or A4, from Centre settings). Opens the print
  // dialog by itself; "Save as PDF" there makes a PDF to send.
  let { params }: { params: Record<string, string> } = $props();

  let bill = $state<Bill | null>(null);
  let centre = $state<CentreSettings | null>(null);
  let failed = $state("");

  $effect(() => {
    Promise.all([get<Bill>(`/api/bills/${params.id}`), get<CentreSettings>("/api/settings")])
      .then(([b, c]) => {
        bill = b;
        centre = c;
        document.title = `${b.invoice_no} · ${b.patient_name}`;
        setTimeout(() => window.print(), 400);
      })
      .catch((e) => (failed = e.message));
  });

  $effect(() => {
    document.body.classList.add("is-printout");
    return () => document.body.classList.remove("is-printout");
  });

  // Paper size from Centre settings (A5 by default).
  $effect(() => {
    if (!centre) return;
    const style = document.createElement("style");
    style.textContent = `@page { size: ${centre.bill_paper === "A4" ? "A4" : "A5"}; margin: 10mm; }`;
    document.head.appendChild(style);
    return () => style.remove();
  });

  const lines = $derived((bill?.items ?? []).filter((l) => l.status !== "cancelled"));
  const payments = $derived(bill?.payments ?? []);
</script>

{#if failed}
  <p class="screen-only" style="padding: 24px">Couldn't load the bill: {failed}</p>
{:else if bill && centre}
  <div class="toolbar-print screen-only">
    <button class="btn btn-primary" onclick={() => window.print()}>Print</button>
    <a class="btn btn-outline" href="/bills/{bill.id}">Back to the bill</a>
  </div>

  <article class="sheet">
    <header class="letterhead">
      {#if session.workspace?.logo_url}<img src={session.workspace.logo_url} alt="" class="logo" />{/if}
      <div class="grow">
        <div class="centre">{centre.legal_name}</div>
        {#if centre.tagline}<div class="tag">{centre.tagline}</div>{/if}
        <div class="contact">{centre.address}</div>
        <div class="contact">{[centre.phones, centre.email].filter(Boolean).join(" · ")}{#if centre.gst_number} · GSTIN {centre.gst_number}{/if}</div>
      </div>
      <div class="doc-type">
        <div class="kind">{Number(bill.due) > 0 ? "Bill" : "Bill / Receipt"}</div>
        <div class="no">{bill.invoice_no}</div>
        <div>{date(bill.bill_date)}</div>
      </div>
    </header>

    {#if bill.status === "cancelled"}<div class="stamp">CANCELLED</div>{/if}

    <section class="patient">
      <div><span class="k">Patient</span><strong>{bill.patient_name}</strong></div>
      <div><span class="k">Age / sex</span>{[bill.patient_age, bill.patient_gender].filter(Boolean).join(" / ") || "—"}</div>
      <div><span class="k">Mobile</span>{bill.patient_mobile || "—"}</div>
      {#if bill.guardian_name}<div><span class="k">C/O</span>{bill.guardian_name}</div>{/if}
      <div><span class="k">Referred by</span>{bill.referring_doctor_name || "Self"}</div>
      {#if bill.patient_address}<div class="wide"><span class="k">Address</span>{bill.patient_address}</div>{/if}
    </section>

    <table class="items">
      <thead><tr><th>#</th><th>Test</th><th class="r">Rate</th><th class="r">Qty</th><th class="r">Amount</th></tr></thead>
      <tbody>
        {#each lines as l, i (l.id)}
          <tr><td>{i + 1}</td><td>{l.test_name}</td><td class="r">{rupees(l.unit_price)}</td><td class="r">{l.quantity}</td><td class="r">{rupees(l.amount)}</td></tr>
        {/each}
      </tbody>
    </table>

    <section class="bottom">
      <div class="paid-list">
        {#if payments.length}
          <div class="k">Payments</div>
          {#each payments as p (p.id)}
            <div>{dateTime(p.received_at)} · {modeLabel(p.mode)}{p.reference ? ` (${p.reference})` : ""} · {p.kind === "refund" ? "refund −" : ""}{rupees(p.amount)}</div>
          {/each}
        {/if}
        {#if bill.notes}<div class="note">{bill.notes}</div>{/if}
      </div>
      <table class="totals">
        <tbody>
          <tr><td>Subtotal</td><td class="r">{rupees(bill.subtotal)}</td></tr>
          {#if Number(bill.discount_amount) > 0}<tr><td>Discount{bill.discount_type === "percent" ? ` (${Number(bill.discount_value)}%)` : ""}</td><td class="r">− {rupees(bill.discount_amount)}</td></tr>{/if}
          <tr class="grand"><td>Total</td><td class="r">{rupees(bill.total)}</td></tr>
          <tr><td>Paid</td><td class="r">{rupees(bill.paid)}</td></tr>
          <tr class="due"><td>Due</td><td class="r">{rupees(bill.due)}</td></tr>
        </tbody>
      </table>
    </section>

    <footer class="foot">
      {#if centre.bill_footer}<p class="terms">{centre.bill_footer}</p>{/if}
      <div class="sign">
        <span>Billed by: {bill.created_by_name || "—"}</span>
        <span class="auth">Authorised signatory</span>
      </div>
      <p class="printed">Printed {dateTime(new Date().toISOString())} · Supreme DMS</p>
    </footer>
  </article>
{:else}
  <p class="screen-only" style="padding: 24px">Preparing the bill…</p>
{/if}

<style>
  :global(body.is-printout) { background: #fff; }
  .toolbar-print { display: flex; gap: 10px; padding: 16px; justify-content: center; }
  .sheet { max-width: 148mm; margin: 0 auto 32px; padding: 8mm; background: #fff; color: #111; font: 11px/1.45 var(--font-sans); position: relative; }
  .letterhead { display: flex; gap: 12px; align-items: flex-start; border-bottom: 2px solid #004aad; padding-bottom: 8px; }
  .logo { width: 56px; height: 56px; object-fit: contain; border-radius: 8px; }
  .grow { flex: 1; min-width: 0; }
  .centre { font: 700 15px/1.2 var(--font-heading); color: #004aad; }
  .tag { font-size: 10px; color: #f58634; font-style: italic; margin-top: 1px; }
  .contact { font-size: 9.5px; color: #333; }
  .doc-type { text-align: right; font-size: 10px; }
  .doc-type .kind { font-weight: 700; text-transform: uppercase; letter-spacing: .06em; color: #004aad; }
  .doc-type .no { font: 600 11px var(--font-mono); margin: 2px 0; }
  .stamp { position: absolute; top: 45%; left: 50%; transform: translate(-50%, -50%) rotate(-18deg); font: 800 44px var(--font-heading);
    color: rgba(198, 40, 40, .18); border: 4px solid rgba(198, 40, 40, .18); padding: 4px 18px; pointer-events: none; }
  .patient { display: grid; grid-template-columns: 1fr 1fr; gap: 3px 16px; padding: 8px 0; border-bottom: 1px solid #ddd; }
  .patient .wide { grid-column: 1 / -1; }
  .k { display: inline-block; min-width: 72px; color: #555; font-size: 9.5px; text-transform: uppercase; letter-spacing: .04em; margin-right: 6px; }
  .items { width: 100%; border-collapse: collapse; margin-top: 8px; }
  .items th { text-align: left; font-size: 9.5px; text-transform: uppercase; letter-spacing: .04em; color: #555; border-bottom: 1px solid #004aad; padding: 4px 4px; }
  .items td { padding: 4px; border-bottom: 1px dotted #ccc; }
  .r { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .bottom { display: flex; gap: 16px; justify-content: space-between; margin-top: 8px; }
  .paid-list { font-size: 9.5px; color: #333; }
  .note { margin-top: 6px; font-style: italic; }
  .totals { border-collapse: collapse; min-width: 52mm; }
  .totals td { padding: 2px 4px; }
  .totals .grand td { border-top: 1px solid #004aad; font-weight: 700; font-size: 12px; padding-top: 4px; }
  .totals .due td { font-weight: 700; }
  .foot { margin-top: 14px; border-top: 1px solid #ddd; padding-top: 6px; }
  .terms { margin: 0 0 14px; font-size: 9px; color: #444; white-space: pre-line; }
  .sign { display: flex; justify-content: space-between; align-items: flex-end; font-size: 10px; }
  .auth { border-top: 1px solid #333; padding-top: 2px; min-width: 40mm; text-align: center; }
  .printed { margin: 8px 0 0; font-size: 8.5px; color: #777; text-align: center; }
  @media print {
    .screen-only { display: none !important; }
    .sheet { margin: 0; padding: 0; max-width: none; }
  }
</style>
