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

<style>
  .sheet { width: 210mm; min-height: 297mm; margin: 0 auto; padding: 12mm 16mm 14mm; background: #fff; color: #111; box-sizing: border-box;
    font: 10.5pt/1.45 Helvetica, Arial, sans-serif; display: flex; flex-direction: column; }
  .letterhead { display: flex; align-items: center; gap: 14px; padding-bottom: 8px; border-bottom: 2px solid var(--brand); }
  .logo { max-width: 28mm; max-height: 22mm; object-fit: contain; }
  h1 { margin: 0; font: 700 17pt/1.2 Helvetica, Arial, sans-serif; color: #111; letter-spacing: 0; }
  .tag, .contact { margin: 2px 0 0; font-size: 8.5pt; color: #444; }
  .patient { width: 100%; margin: 8px 0; border: 1px solid #999; border-collapse: collapse; font-size: 9.5pt; }
  .patient td { padding: 2px 6px; width: 50%; }
  .title { text-align: center; text-transform: uppercase; font: 700 13pt Helvetica, Arial, sans-serif; margin: 8px 0 6px; color: #111; }
  .amended { color: #b42318; margin: 0 0 6px; }
  .draft { color: #b42318; border: 1px solid #b42318; padding: 4px 8px; margin: 0 0 6px; }
  h3 { font: 700 10.5pt Helvetica, Arial, sans-serif; margin: 10px 0 2px; color: #333; }
  p { margin: 0 0 4px; }
  .html :global(p) { margin: 0 0 4px; }
  .html :global(ul), .html :global(ol) { margin: 0 0 4px; padding-left: 20px; }
  .html :global(h2), .html :global(h3), .html :global(h4) { font-size: 10.5pt; margin: 6px 0 2px; }
  .html :global(table) { border-collapse: collapse; margin: 4px 0; }
  .html :global(td), .html :global(th) { border: 1px solid #999; padding: 2px 6px; }
  .impression { font-weight: 600; }
  .end { margin-top: auto; padding-top: 16px; display: flex; justify-content: space-between; align-items: flex-end; gap: 20px; break-inside: avoid; }
  .qr { display: flex; align-items: center; gap: 8px; max-width: 70mm; font-size: 8pt; color: #444; }
  .sign { display: flex; flex-direction: column; align-items: flex-end; text-align: right; font-size: 9.5pt; }
  .sign img { max-width: 45mm; max-height: 18mm; object-fit: contain; margin-bottom: 2px; }
  .verify { font-size: 7.5pt; color: #555; margin-top: 8px; }
  @media print { .sheet { width: auto; min-height: calc(297mm - 0.1mm); margin: 0; padding: 10mm 14mm; } }
  @page { size: A4; margin: 0; }
</style>
