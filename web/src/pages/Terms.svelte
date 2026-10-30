<script lang="ts">
  import Credit from "../components/Credit.svelte";
  import { session } from "../lib/session.svelte";

  // Terms and conditions: open to everyone, signed in or not (linked from sign-in and the sidebar).
  const UPDATED = "10 October 2026";
  const back = $derived(session.me ? "/" : "/login");

  const sections: { id: string; title: string; body: string[] }[] = [
    { id: "about", title: "1. About these terms", body: [
      "CIDMS is software for diagnostic centres, clinics and OPDs to bill patients, track tests, write reports and view medical images. These terms apply to every centre that uses it and to every person who signs in.",
      "By signing in you agree to these terms on behalf of yourself and the centre you work for. If you don't agree, don't use the service.",
    ] },
    { id: "accounts", title: "2. Accounts and access", body: [
      "Each centre has its own workspace at its own address. The centre's owner decides who gets an account and what each person may do.",
      "Keep your password to yourself and sign out on shared computers. Tell your centre's owner straight away if you think someone else has used your account.",
      "Accounts are locked for a while after repeated wrong passwords. Every sign-in and important action is recorded in the centre's activity log.",
    ] },
    { id: "data", title: "3. Patient information", body: [
      "Patient information belongs to the centre. The centre is responsible for collecting it lawfully, for telling patients how it's used, and for getting their consent where the law requires it (including under India's Digital Personal Data Protection Act, 2023).",
      "We process patient information only to run the service for the centre. We don't sell it, share it for advertising, or use it for anything else.",
      "Each centre can only ever see its own data: this is enforced in the database itself, not just in the screens.",
      "Use patient information only for the patient's care and the centre's work. Looking up records without a reason is not allowed and is visible in the activity log.",
    ] },
    { id: "reports", title: "4. Reports, images and messages", body: [
      "Medical reports are written and signed by the centre's qualified staff. CIDMS stores and prints them but does not check their medical content; the signing doctor is responsible for it.",
      "Images viewed in the DICOM viewer are for review alongside the report. Diagnostic decisions should be made on equipment and displays suited to that purpose.",
      "When a report is sent to a patient on WhatsApp or by email, it goes to the number or address the centre has on record. The centre is responsible for checking it is correct.",
    ] },
    { id: "billing", title: "5. Bills and payments", body: [
      "Bills are numbered in sequence and cannot be deleted; a mistaken bill is cancelled with a reason and stays on record. Payments and refunds are kept as separate entries.",
      "The centre is responsible for its prices, discounts and taxes, and for the bills it issues to patients.",
    ] },
    { id: "subscription", title: "6. Subscription", body: [
      "Centres pay for CIDMS on the plan agreed with us. Payments are collected directly (bank transfer, UPI or cheque) and recorded against the centre's account.",
      "If payment is overdue we'll remind the centre first. A workspace may be suspended after the notice period in the agreement; its data is kept and returned on request.",
    ] },
    { id: "use", title: "7. Acceptable use", body: [
      "Don't try to reach another centre's data, get around permissions, overload the service, or upload anything harmful.",
      "Don't share screenshots or exports of patient information outside the people who need it for the patient's care.",
    ] },
    { id: "availability", title: "8. Availability and backups", body: [
      "We work to keep the service running and back up data regularly, but we can't promise it will never be interrupted. Planned maintenance is announced in advance where possible.",
      "Keep printed or exported copies of anything you must have during an outage.",
    ] },
    { id: "liability", title: "9. Liability", body: [
      "The service is provided as described in the centre's agreement. To the extent the law allows, we aren't liable for indirect losses, or for decisions made using information entered by the centre.",
    ] },
    { id: "end", title: "10. Ending the service", body: [
      "A centre can stop using CIDMS at any time. On request we'll provide an export of its bills, patients and reports, then delete its data after the period the law requires records to be kept.",
    ] },
    { id: "changes", title: "11. Changes to these terms", body: [
      "We may update these terms. The date at the top shows the latest version, and important changes are announced in the app before they apply.",
    ] },
    { id: "contact", title: "12. Questions", body: [
      "Questions about these terms or about patient information: ask your centre's owner first, who can contact us on your behalf.",
    ] },
  ];
</script>

<div class="terms-page">
  <header class="terms-head">
    <a class="btn btn-ghost btn-sm" href={back}>← {session.me ? "Back to the app" : "Back to sign in"}</a>
    <span class="eyebrow">{session.workspace?.name ?? "CIDMS"}</span>
    <h1 class="page-title">Terms and conditions</h1>
    <p class="text-muted">Last updated {UPDATED}</p>
  </header>

  <div class="terms-body">
    <nav class="toc card" aria-label="Contents">
      <ol>{#each sections as s (s.id)}<li><a href="#{s.id}" onclick={(e) => { e.preventDefault(); document.getElementById(s.id)?.scrollIntoView({ behavior: "smooth" }); }}>{s.title.replace(/^\d+\.\s/, "")}</a></li>{/each}</ol>
    </nav>
    <article class="card card-content">
      {#each sections as s (s.id)}
        <section id={s.id}>
          <h2>{s.title}</h2>
          {#each s.body as para, i (i)}<p>{para}</p>{/each}
        </section>
      {/each}
    </article>
  </div>

  <footer class="terms-foot"><Credit /></footer>
</div>

<style src="./styles/Terms.css"></style>
