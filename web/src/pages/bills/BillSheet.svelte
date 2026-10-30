<script lang="ts">
  import type { Bill } from "../../lib/bill-types";

  // The bill laid out exactly like Supreme's old "Bill / Receipt" (Verdana, black on white, the centre's name
  // and phones centred on top, a QR code, the patient block, the tests table, then sub total, due, discount,
  // paid, received by, total, the notes and the signatory). Shared by the staff print view (BillPrint.svelte,
  // the full CentreSettings) and the patient's public page (PublicBill.svelte, just these four fields).
  let { bill, centre, patientNo, qr = "", provisional = false }: {
    bill: Bill; centre: { legal_name: string; address: string; phones: string; bill_footer: string }; patientNo: string;
    qr?: string; provisional?: boolean;
  } = $props();

  const lines = $derived((bill.items ?? []).filter((l) => l.status !== "cancelled"));
  const notes = $derived((centre.bill_footer ?? "").split("\n").map((l) => l.trim()).filter(Boolean));
  const amount = (v: string | number) => Number(v).toFixed(2);
  const title = (g: string) => (g === "male" ? "Mr." : "Mrs.");
  const ageText = $derived((bill.patient_age ?? "").replace(/\s*Y$/i, " yrs."));
  const billDate = $derived(bill.bill_date.split("-").reverse().join("-"));
</script>

<div class="receipt">
  <div class="head">
    <h1>{centre.legal_name}</h1>
    <p>{centre.address}</p>
    {#if centre.phones}<p>Mobile: {centre.phones}</p>{/if}
  </div>

  <table class="top">
    <tbody><tr>
      <th class="l">Invoice No. : {bill.legacy_no ? `#000${bill.legacy_no}` : bill.invoice_no}</th>
      <th class="c">Bill / Receipt</th>
      <th class="r">Date : {billDate}</th>
    </tr></tbody>
  </table>
  <hr />
  {#if provisional}<p class="provisional">Provisional bill, made offline. The final bill number is given when it reaches CIDMS.</p>{/if}

  <table class="patient">
    <tbody>
      <tr>
        <td><span class="k">Patient Name</span>: <strong class="up">{title(bill.patient_gender)}{bill.patient_name}</strong>
          <span class="gap"></span><span class="up">{ageText}/{bill.patient_gender}</span></td>
        <td rowspan="4" class="qr">{#if qr}<img src={qr} alt="" width="70" height="70" />{/if}</td>
      </tr>
      <tr><td><span class="k">Patient ID</span>: {patientNo}</td></tr>
      <tr><td><span class="k">Mobile</span>: {bill.patient_mobile ? `+91${bill.patient_mobile.replace(/\D/g, "").slice(-10)}` : ""}
        <span class="gap2"></span><span class="k2">Consultant :</span> <span class="up">{bill.referring_doctor_name || "SELF"}</span></td></tr>
      <tr><td><span class="k">Address</span>: {bill.patient_address}</td></tr>
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

<style src="./styles/BillSheet.css"></style>
