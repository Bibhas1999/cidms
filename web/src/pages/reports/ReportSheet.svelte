<script lang="ts">
  import QRCode from "qrcode";
  import type { ReportPrint } from "../../lib/report-types";

  // The report on A4, as printed and as the patient sees it online: the centre's letterhead, the patient block,
  // title, technique, findings, impression, the signature, "Amended" when it was changed after signing, the QR
  // code for the patient's link and a verification line. Same layout as the server's PDF (app/services/report_pdf.py).
  let { data, logoUrl = "/api/workspace/logo" }: { data: ReportPrint; logoUrl?: string } = $props();

  let qr = $state("");
  let logoOk = $state(true);
  $effect(() => {
    qr = "";
    if (data.public_url) QRCode.toDataURL(data.public_url, { margin: 0, width: 180 }).then((u) => (qr = u)).catch(() => {});
  });

  const d = (iso: string) => iso.slice(0, 10).split("-").reverse().join("-");
  const when = (iso: string | null) => iso ? new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short" }).format(new Date(iso)) : "";
  const contact = $derived([data.centre.address.replace(/\n/g, ", "), data.centre.phones && `Phone: ${data.centre.phones}`, data.centre.email].filter(Boolean).join(" · "));
</script>

<article class="sheet" style="--brand: {data.centre.brand_color || '#0f6e6e'}">
  <header class="letterhead">
    {#if data.centre.has_logo && logoOk}<img class="logo" src={logoUrl} alt="" onerror={() => (logoOk = false)} />{/if}
    <div>
      <h1>{data.centre.legal_name}</h1>
      {#if data.centre.tagline}<p class="tag">{data.centre.tagline}</p>{/if}
      {#if contact}<p class="contact">{contact}</p>{/if}
    </div>
  </header>

  <table class="patient">
    <tbody>
      <tr><td><b>Patient:</b> {data.item.patient_name}</td><td><b>Age / Sex:</b> {[data.item.patient_age, data.item.patient_gender].filter(Boolean).join(" / ") || "—"}</td></tr>
      <tr><td><b>Patient ID:</b> {data.patient_no || "—"}</td><td><b>Bill no.:</b> {data.item.invoice_no}</td></tr>
      <tr><td><b>Referred by:</b> {data.item.referring_doctor_name || "Self"}</td><td><b>Date:</b> {d(data.item.bill_date)}</td></tr>
      {#if data.item.accession_no}<tr><td><b>Accession no.:</b> {data.item.accession_no}</td><td><b>Test:</b> {data.item.test_name}</td></tr>{/if}
    </tbody>
  </table>

  <h2 class="title">{data.title || data.item.test_name}</h2>
  {#if data.amended}<p class="amended"><b>AMENDED REPORT</b>{#if data.amend_reason} — {data.amend_reason}{/if}</p>{/if}
  {#if !data.is_final}<p class="draft"><b>DRAFT — NOT SIGNED.</b> Not valid as a report.</p>{/if}

  {#if data.technique}<h3>Technique</h3><p>{data.technique}</p>{/if}
  <!-- findings and impression are cleaned on the server to a small set of safe tags before saving -->
  {#if data.findings}<h3>Findings</h3><div class="html">{@html data.findings}</div>{/if}
  {#if data.impression}<h3>Impression</h3><div class="html impression">{@html data.impression}</div>{/if}

  <footer class="end">
    <div class="qr">
      {#if qr}<img src={qr} alt="QR code for this report online" width="90" height="90" /><span>Scan to view or download this report online.</span>{/if}
    </div>
    {#if data.signer}
      <div class="sign">
        {#if data.signer.signature}<img src={data.signer.signature} alt="Signature of {data.signer.name}" />{/if}
        <b>{data.signer.name}</b>
        {#if data.signer.degree}<span>{data.signer.degree}</span>{/if}
        {#if data.signer.registration_no}<span>Reg. no. {data.signer.registration_no}</span>{/if}
      </div>
    {/if}
  </footer>

  <p class="verify">Report {data.verification}{#if data.signer && data.signed_at} · electronically signed by {data.signer.name} on {when(data.signed_at)}{/if}</p>
  {#if data.centre.report_footer}<p class="verify">{data.centre.report_footer}</p>{/if}
</article>

<style src="./styles/ReportSheet.css"></style>
