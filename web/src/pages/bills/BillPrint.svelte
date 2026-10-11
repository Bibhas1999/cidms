<script lang="ts">
  import QRCode from "qrcode";
  import { get } from "../../lib/api";
  import type { Bill, Patient } from "../../lib/bill-types";
  import type { CentreSettings } from "../../lib/types";

  // The printed bill, laid out exactly like Supreme's old "Bill / Receipt" (Verdana, black on white, the
  // centre's name and phones centred on top, a QR code, the patient block, the tests table, then sub total,
  // due, discount, paid, received by, total, the notes and the signatory). Opens the print dialog by itself.
  let { params }: { params: Record<string, string> } = $props();

  let bill = $state<Bill | null>(null);
  let centre = $state<CentreSettings | null>(null);
  let patientNo = $state("");
  let qr = $state("");
  let failed = $state("");

  $effect(() => {
    document.body.classList.add("is-printout");
    return () => document.body.classList.remove("is-printout");
  });

  $effect(() => {
    Promise.all([get<Bill>(`/api/bills/${params.id}`), get<CentreSettings>("/api/settings")])
      .then(async ([b, c]) => {
        bill = b;
        centre = c;
        document.title = `${b.invoice_no} · ${b.patient_name}`;
        get<Patient>(`/api/patients/${b.patient_id}`).then((p) => (patientNo = p.patient_no)).catch(() => {});
        // The QR opens this bill in Supreme DMS (sign-in needed), instead of the old public download link.
        qr = await QRCode.toDataURL(`${location.origin}/bills/${b.id}`, { margin: 0, width: 140 });
        setTimeout(() => window.print(), 500);
      })
      .catch((e) => (failed = e.message));
  });

  const lines = $derived((bill?.items ?? []).filter((l) => l.status !== "cancelled"));
  const notes = $derived((centre?.bill_footer ?? "").split("\n").map((l) => l.trim()).filter(Boolean));
  const amount = (v: string | number) => Number(v).toFixed(2);
  const title = (g: string) => (g === "male" ? "Mr." : "Mrs.");
  const ageText = $derived((bill?.patient_age ?? "").replace(/\s*Y$/i, " yrs."));
  const billDate = $derived(bill ? bill.bill_date.split("-").reverse().join("-") : "");
</script>

{#if failed}
  <p class="screen-only" style="padding: 24px">Couldn't load the bill: {failed}</p>
{:else if bill && centre}
  <div class="screen-only bar">
    <button class="btn btn-primary" onclick={() => window.print()}>Print</button>
    <a class="btn btn-outline" href="/bills/{bill.id}">Back to the bill</a>
  </div>

  <div class="receipt">
    <div class="head">
      <h1>{centre.legal_name}</h1>
      <p>{centre.address}</p>
      {#if centre.phones}<p>Mobile: {centre.phones}</p>{/if}
    </div>

    <table class="top">
      <tbody><tr>
        <th class="l">Invoice No. - {bill.legacy_no ? `#000${bill.legacy_no}` : bill.invoice_no}</th>
        <th class="c">Bill / Receipt</th>
        <th class="r">Date-{billDate}</th>
      </tr></tbody>
    </table>
    <hr />

    <table class="patient">
      <tbody>
        <tr>
          <td><span class="k">Patient Name :</span> <strong class="up">{title(bill.patient_gender)}{bill.patient_name}</strong>
            <span class="gap"></span><span class="up">{ageText}/{bill.patient_gender}</span></td>
          <td rowspan="4" class="qr">{#if qr}<img src={qr} alt="" width="70" height="70" />{/if}</td>
        </tr>
        <tr><td><span class="k">Patient ID</span><span class="pad"></span>: {patientNo}</td></tr>
        <tr><td><span class="k">Mobile</span><span class="pad2"></span>: {bill.patient_mobile ? `+91${bill.patient_mobile.replace(/\D/g, "").slice(-10)}` : ""}
          <span class="gap2"></span><span class="k">Consultant : </span>{bill.referring_doctor_name || "SELF"}</td></tr>
        <tr><td><span class="k">Address</span><span class="pad"></span>: {bill.patient_address}</td></tr>
      </tbody>
    </table>

    <table class="items">
      <thead><tr><th style="width: 5%">#</th><th style="width: 50%">Test Name</th><th>Qty</th><th>Unit Amount</th><th>Total Amount</th></tr></thead>
      <tbody>
        {#each lines as l, i (l.id)}
          <tr><td>{i + 1}</td><td>{l.test_name}</td><td class="mono">{l.quantity}</td><td class="mono">{amount(l.unit_price)}</td><td class="mono">{amount(l.amount)}</td></tr>
        {/each}
        <tr><td colspan="4" class="mono b r subt">Sub Total :</td><td class="mono b subt">{amount(bill.subtotal)}</td></tr>
        <tr>
          <td></td>
          <td class="due">Due Amount : Rs - {amount(bill.due)}</td>
          {#if Number(bill.discount_amount) > 0}<td colspan="2" class="mono r">Disc :</td><td class="mono">{amount(bill.discount_amount)}</td>{:else}<td></td><td></td>{/if}
        </tr>
        <tr><td></td><td colspan="3" class="mono r">Paid Amt :</td><td class="mono">{amount(bill.paid)}</td></tr>
        <tr><td colspan="4" class="line"></td><td class="line"></td></tr>
        <tr><td></td><td>Recieved by - {bill.created_by_name}</td><td></td><td class="mono b r">Total Amt :</td><td class="mono b">{amount(bill.total)}</td></tr>
      </tbody>
    </table>

    {#if bill.status === "cancelled"}<p class="cancelled">CANCELLED: {bill.cancel_reason}</p>{/if}

    <div class="foot">
      {#if notes.length}
        <h6>Note :</h6>
        <ol>{#each notes as n, i (i)}<li>{n}</li>{/each}</ol>
      {/if}
      <div class="sign"><span></span><span>Thank you for visiting us.</span><span class="signatory">Authorized Signatory</span></div>
    </div>
  </div>
{:else}
  <p class="screen-only" style="padding: 24px">Preparing the bill…</p>
{/if}

<style>
  :global(body.is-printout) { background: #fff !important; }
  .bar { display: flex; gap: 10px; justify-content: center; padding: 16px; }
  .receipt { width: 190mm; margin: 0 auto 32px; padding: 8mm 10mm; background: #fff; color: #000; font-family: Verdana, Geneva, Tahoma, sans-serif; font-size: 13px; }
  .head { text-align: center; }
  .head h1 { font-family: Verdana, Geneva, Tahoma, sans-serif; font-size: 26px; font-weight: 700; color: #000; margin: 0 0 4px; letter-spacing: 0; }
  .head p { font-family: "Courier New", Courier, monospace; font-size: 14px; margin: 0; }
  table { width: 100%; border-collapse: collapse; }
  .top th { font-family: Verdana, Geneva, Tahoma, sans-serif; padding: 6px 0 2px; color: #000; background: none; font-size: 13px; }
  .top .l { text-align: left; width: 30%; } .top .c { text-align: center; font-size: 18px; width: 40%; } .top .r { text-align: right; font-size: 12px; width: 30%; }
  hr { margin: 0; border: 0; border-top: 1px solid #000; }
  .patient td { padding: 3px 0; font-size: 13px; vertical-align: top; }
  .patient .k { font-weight: bold; }
  .up { text-transform: uppercase; }
  .gap { display: inline-block; width: 40px; } .gap2 { display: inline-block; width: 48px; }
  .pad { display: inline-block; width: 40px; } .pad2 { display: inline-block; width: 66px; }
  .qr { text-align: right; width: 90px; }
  .items { margin-top: 6px; border-top: 1px solid #000; }
  .items th { text-align: left; font-size: 13px; font-family: Verdana; border-bottom: 1px solid #000; padding: 2px; color: #000; background: none; font-weight: bold; }
  .items td { font-size: 13px; padding: 7px 2px 5px; }
  .mono { font-family: "Courier New", Courier, monospace; }
  .b { font-weight: bold; } .r { text-align: right; }
  .subt { border-top: 1px solid #000; }
  .due { text-align: right; font-size: 17px; font-weight: bold; padding-right: 30px !important; }
  .line { border-bottom: 1px solid #000; padding: 0 !important; }
  .cancelled { margin: 10px 0 0; font-weight: bold; color: #b00; }
  .foot h6 { margin: 8px 0 2px; font-size: 12px; }
  .foot ol { font-size: 12px; font-weight: bold; margin: 0; padding-left: 20px; }
  .sign { display: flex; justify-content: space-between; align-items: flex-end; margin-top: 30px; font-size: 13px; font-weight: bold; }
  .signatory { border-top: 1px solid #000; padding-top: 2px; }
  /* Screen only, on phones and small tablets: the same receipt, fitted to the screen (paper is unchanged). */
  @media screen and (max-width: 800px) {
    .bar { position: sticky; top: 0; z-index: 2; background: var(--card); border-bottom: 1px solid var(--border); padding: 10px 12px;
      padding-top: max(10px, env(safe-area-inset-top)); }
    .bar .btn { flex: 1 1 0; height: 44px; }
    .receipt { width: 100%; max-width: 190mm; box-sizing: border-box; margin: 12px auto 24px; padding: 14px 12px; font-size: 12px;
      box-shadow: 0 1px 3px rgb(0 0 0 / .12); overflow-wrap: anywhere; }
    .head h1 { font-size: 20px; }
    .head p { font-size: 12px; }
    .top .c { font-size: 15px; } .top .l, .top .r { font-size: 11px; }
    .patient td, .items td, .items th { font-size: 12px; }
    .gap, .gap2 { width: 12px; } .pad { width: 12px; } .pad2 { width: 24px; }
    .due { font-size: 14px; padding-right: 8px !important; }
    :global(body.is-printout) { background: var(--muted) !important; }
  }
  @media print {
    .screen-only { display: none !important; }
    .receipt { width: auto; margin: 0; padding: 0; }
    @page { size: A4; margin: 15px 12mm 12mm; }
  }
</style>
