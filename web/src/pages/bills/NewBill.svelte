<script lang="ts">
  import { confirmDialog } from "../../lib/confirm.svelte";
  import { z } from "zod";
  import Button from "../../components/Button.svelte";
  import Combobox from "../../components/Combobox.svelte";
  import DataTable from "../../components/DataTable.svelte";
  import FormDialog from "../../components/FormDialog.svelte";
  import Field from "../../components/Field.svelte";
  import FormErrors from "../../components/FormErrors.svelte";
  import Icon from "../../components/Icon.svelte";
  import InfoTip from "../../components/InfoTip.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import PhoneInput from "../../components/PhoneInput.svelte";
  import TestSelect from "../../components/TestSelect.svelte";
  import { ApiError, get, newRequestKey, post } from "../../lib/api";
  import { PAYMENT_MODES, type Bill, type Doctor, type LabTest, type Patient, type PaymentMode } from "../../lib/bill-types";
  import { autosaveDraft, clearDraft, readDraft, savedAgo, type Draft } from "../../lib/drafts.svelte";
  import { confirmLeave } from "../../lib/leave";
  import { connection } from "../../lib/connection.svelte";
  import { cachedSettings, offline, saveOfflineBill, searchCachedDoctors, searchCachedPatients, withOffline } from "../../lib/offline.svelte";
  import { Form } from "../../lib/form.svelte";
  import { rupees } from "../../lib/format";
  import { formatPhone, splitPhone } from "../../lib/phone";
  import { navigate, router, setBeforeLeave } from "../../lib/router.svelte";
  import { optionalPersonName, optionalText, personName, phone, referrerName, submitting, wholeNumber } from "../../lib/schemas";
  import { session } from "../../lib/session.svelte";
  import { notify, notifyError } from "../../lib/toast.svelte";
  import { GENDER_LABELS, type CentreSettings, type Page } from "../../lib/types";

  // One screen for the front desk: find or add the patient, the referring doctor, the tests, the discount
  // and what's paid now. Prices come from the catalogue; the server works out every total again.
  // On phones the summary goes under the form and a bar along the bottom keeps the total and Save in reach.

  // ---------- patient ----------
  let patient = $state<Patient | null>(null);
  let addingPatient = $state(false);
  let patientQuery = $state("");
  let family = $state<Patient[]>([]);

  const patientSchema = z.object({
    name: personName("Enter the patient's name."),
    mobile: phone(false),
    age_years: wholeNumber({ min: 0, max: 130, required: "Enter the age in years.", label: "the age in years" }),
    gender: z.string().refine((v) => v in GENDER_LABELS, "Choose the gender."),
    guardian_name: optionalPersonName(200, "The guardian's name"),
    address: optionalText(500),
  });
  const patientLabels = { name: "Full name", mobile: "Mobile", age_years: "Age", gender: "Gender", guardian_name: "Guardian", address: "Address" };
  let pendingPrint = false;
  const np = new Form({
    schema: patientSchema,
    initial: { name: "", mobile: "", age_years: null as number | null, gender: "", guardian_name: "", address: "" },
    onSubmit: (data) => saveBill(pendingPrint, data),
  });

  const preset = router.query.get("patient");
  $effect(() => {
    if (preset) get<Patient>(`/api/patients/${preset}`).then((p) => (patient = p)).catch(() => {});
  });

  // Offline, searches use this computer's copy (lib/offline): the most recent patients, all tests and doctors.
  const searchPatients = withOffline<Patient>((q, page, size, signal) => get<Page<Patient>>("/api/patients", { search: q, page, size }, signal), searchCachedPatients);

  let familyTimer: ReturnType<typeof setTimeout>;
  function onMobile() {
    np.field("mobile").oninput();
    clearTimeout(familyTimer);
    const { number } = splitPhone(np.values.mobile);
    if (number.length < 8) { family = []; return; }
    familyTimer = setTimeout(() => get<Patient[]>("/api/patients/same-mobile", { mobile: np.values.mobile }).then((r) => (family = r)).catch(() => {}), 250);
  }

  function startNewPatient() {
    addingPatient = true;
    patient = null;
    np.reset();
    const q = patientQuery.trim();
    if (/^[+\d\s]{6,}$/.test(q)) np.values.mobile = q.startsWith("+") ? q.replace(/\s/g, "") : `+91${q.replace(/\D/g, "").slice(-10)}`;
    else if (q) np.values.name = q;
    onMobile();
  }

  // ---------- doctor ----------
  let doctorText = $state("");
  let doctor = $state<Doctor | null>(null);
  const searchDoctors = withOffline<Doctor>((q, page, size, signal) => get<Page<Doctor>>("/api/doctors", { search: q, active: true, page, size }, signal), searchCachedDoctors);

  // A doctor not in the list yet: add them in a dialog (saved to the list at once) and they're chosen for this bill.
  let addingDoctor = $state(false);
  const doctorForm = new Form({
    schema: z.object({ name: referrerName("Enter the doctor's or hospital's name."), qualification: optionalText(200), phone: phone(false) }),
    initial: { name: "", qualification: "", phone: "" },
    onSubmit: async (v) => {
      try {
        const d = await post<Doctor>("/api/doctors", v);
        doctor = d;
        doctorText = d.name;
        addingDoctor = false;
        notify(`${d.name} is added to your doctors and hospitals and chosen for this bill.`);
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) { doctorForm.errors = { name: "This name is already in your list: search for it instead." }; return; }
        throw e;
      }
    },
  });

  function startNewDoctor() {
    doctorForm.reset({ name: doctorText.trim(), qualification: "", phone: "" });
    addingDoctor = true;
  }

  // ---------- tests ----------
  interface Line { test: LabTest; quantity: number }
  let lines = $state<Line[]>([]);
  const onBill = $derived(new Set(lines.map((l) => l.test.id)));

  // Ticking a test in the drop-down puts it on the bill straight away; unticking (or Remove) takes it off.
  function toggleTest(t: LabTest, on: boolean) {
    if (on && !onBill.has(t.id)) lines.push({ test: t, quantity: 1 });
    if (!on) { lines = lines.filter((l) => l.test.id !== t.id); const { [t.id]: _, ...rest } = qtyProblems; qtyProblems = rest; }
    errors = { ...errors, lines: "" };
  }
  // A quantity outside 1–20 (or not a whole number) shows an error under the tests at once and the bill can't be
  // saved until it's put right; the line keeps its last good quantity meanwhile.
  let qtyProblems = $state<Record<string, string>>({});
  function setQty(id: string, n: number) {
    const l = lines.find((x) => x.test.id === id);
    if (!l) return;
    const { [id]: _, ...rest } = qtyProblems;
    if (!Number.isInteger(n) || n < 1 || n > 20) { qtyProblems = { ...rest, [id]: `${l.test.name}: the quantity must be a whole number from 1 to 20.` }; return; }
    qtyProblems = rest;
    l.quantity = n;
  }

  // ---------- money ----------
  // Discount: % or ₹ (radio), and the amount; an empty or zero amount means no discount.
  let discountKind = $state<"percent" | "amount">("percent");
  let discountValue = $state("");
  const discountType = $derived<"none" | "percent" | "amount">(Number(discountValue) > 0 ? discountKind : "none");
  let payNow = $state("");
  let payMode = $state<PaymentMode>("cash");
  let payRef = $state("");
  let notes = $state("");
  let hold = $state(false);
  let maxDiscount = $state<number | null>(null);
  $effect(() => {
    get<CentreSettings & { max_discount_percent?: string }>("/api/settings").catch(() => cachedSettings())
      .then((s) => { if (s?.max_discount_percent !== undefined) maxDiscount = Number(s.max_discount_percent); }).catch(() => {});
  });
  const overLimitOk = $derived(session.can("billing.discount_over_limit"));

  const round2 = (n: number) => Math.round(n * 100) / 100;
  const subtotal = $derived(round2(lines.reduce((s, l) => s + Number(l.test.price) * l.quantity, 0)));
  const discount = $derived(
    discountType === "percent" ? round2((subtotal * Math.min(100, Number(discountValue) || 0)) / 100)
      : discountType === "amount" ? Math.min(subtotal, round2(Number(discountValue) || 0)) : 0,
  );
  const total = $derived(round2(subtotal - discount));
  const paying = $derived(Math.min(total, round2(Number(payNow) || 0)));
  // Paid now can't be more than the bill. Typed above it (or the total drops below it after a test is taken off or
  // the discount goes up), the amount stays as typed and an error shows under the box at once; the bill can't be
  // saved until it's put right ("Full amount" sets it to the total).
  // The discount box, checked as it's typed: a percentage above 100, rupees above the subtotal, or less than 0.
  const discountProblem = $derived.by(() => {
    if (discountValue === "" || discountValue === null) return "";
    const n = Number(discountValue);
    if (!Number.isFinite(n) || n < 0) return "Enter a discount of 0 or more.";
    if (discountKind === "percent" && n > 100) return "A discount can't be more than 100%.";
    if (discountKind === "amount" && round2(n) > subtotal) return `A discount can't be more than the subtotal, ${rupees(subtotal)}.`;
    return "";
  });
  const payTooMuch = $derived(payNow !== "" && !Number.isNaN(Number(payNow)) && round2(Number(payNow)) > total);
  $effect(() => { if (payNow !== "" && Number(payNow) < 0) payNow = ""; });
  const dueAfter = $derived(round2(total - paying));
  const overLimit = $derived(maxDiscount !== null && subtotal > 0 && discount * 100 > subtotal * maxDiscount);

  const discountTip = $derived(
    `A percentage of the subtotal, or a fixed amount in rupees. ${maxDiscount !== null ? `The centre allows up to ${maxDiscount}% ` : "The centre sets a limit "}` +
    (overLimitOk ? "(you may go above it)." : "without the owner's permission; ask the owner for more."),
  );

  // ---------- save ----------
  let errors = $state<Record<string, string>>({});
  let saving = $state(false);
  let requestKey: string = newRequestKey();
  // The summary (discount, payment, hold, save) waits for the first test: until then there's nothing to price.
  const noTests = $derived(!lines.length);
  const dirty = $derived(!!(patient || addingPatient || lines.length || doctorText.trim() || notes.trim() || discountValue || payNow));

  // ---------- draft ----------
  // Everything typed is kept on this computer as it's typed (lib/drafts), so leaving the page, closing the tab
  // or a power cut loses nothing: New bill opens with it again. The request key goes with it, so a bill whose
  // save was already on its way is never made twice.
  const DRAFT = "new-bill";
  interface BillDraft {
    patient: Patient | null; addingPatient: boolean; patientQuery: string; np: typeof np.values;
    doctorText: string; doctor: Doctor | null; lines: Line[];
    discountKind: "percent" | "amount"; discountValue: string; payNow: string; payMode: PaymentMode; payRef: string;
    notes: string; hold: boolean; requestKey: string;
  }
  let finished = false;                                  // saved or thrown away: stop keeping a draft
  let restored = $state<Draft<BillDraft> | null>(null);  // the draft this page opened with
  let waiting = $state<Draft<BillDraft> | null>(null);   // a draft not opened (the page came for another patient)

  function applyDraft(d: BillDraft) {
    patient = d.patient; addingPatient = d.addingPatient; patientQuery = d.patientQuery;
    if (d.addingPatient) np.reset(d.np);
    doctorText = d.doctorText; doctor = d.doctor; lines = d.lines;
    discountKind = d.discountKind; discountValue = d.discountValue; payNow = d.payNow; payMode = d.payMode; payRef = d.payRef;
    notes = d.notes; hold = d.hold; requestKey = d.requestKey || requestKey;
  }
  {
    const d = readDraft<BillDraft>(DRAFT);
    if (d && !preset) { applyDraft(d.value); restored = d; }
    else if (d) waiting = d;
  }
  function openWaiting() {
    if (!waiting) return;
    applyDraft(waiting.value);
    restored = waiting;
    waiting = null;
  }
  /** "Clear draft": after asking, empty the form and forget the draft kept on this computer. */
  async function clearTheDraft() {
    if (!(await confirmDialog({ title: "Clear this draft?", tone: "danger", confirmLabel: "Clear draft",
                                message: "Everything typed on this bill goes, and the draft kept on this computer is removed." }))) return;
    startAfresh();
    notify("Draft cleared.");
  }
  function startAfresh() {
    clearDraft(DRAFT);
    patient = null; addingPatient = false; patientQuery = ""; np.reset();
    doctorText = ""; doctor = null; lines = [];
    discountKind = "percent"; discountValue = ""; payNow = ""; payMode = "cash"; payRef = ""; notes = ""; hold = false;
    requestKey = newRequestKey(); errors = {}; restored = null; waiting = null;
  }
  autosaveDraft<BillDraft>(DRAFT, () => ({
    patient, addingPatient, patientQuery, np: np.values, doctorText, doctor, lines,
    discountKind, discountValue, payNow, payMode, payRef, notes, hold, requestKey,
  }), (v) => !v.patient && !v.addingPatient && !v.lines.length && !v.doctorText.trim() && !v.notes.trim() && !v.discountValue && !v.payNow,
  { paused: () => finished || !!waiting });

  $effect(() => {
    setBeforeLeave(dirty && !saving ? confirmLeave({
      title: "Leave this bill?",
      message: "It isn't saved yet. It's kept as a draft on this computer: open New bill again to finish it.",
      leaveLabel: "Leave, keep the draft", stayLabel: "Stay",
      discard: { label: "Discard the bill", run: () => { finished = true; clearDraft(DRAFT); } },
    }) : null);
    return () => setBeforeLeave(null);
  });

  function save(print: boolean) {
    if (saving || np.submitting) return;
    errors = {};
    if (!patient && !addingPatient) { errors = { patient: "Choose a patient or add a new one." }; document.getElementById("patient-search")?.focus(); return; }
    if (addingPatient) { pendingPrint = print; void np.submit(); return; }
    void saveBill(print, null);
  }

  async function saveBill(print: boolean, newPatient: z.output<typeof patientSchema> | null) {
    if (!lines.length) { errors = { lines: "Add at least one test." }; document.getElementById("nb-test")?.focus(); return; }
    // These errors are already showing next to their boxes: go to the first one.
    const firstQty = Object.keys(qtyProblems)[0];
    if (firstQty) { document.querySelector<HTMLInputElement>(`input[aria-label="Quantity of ${lines.find((l) => l.test.id === firstQty)?.test.name}"]`)?.focus(); return; }
    if (discountProblem) { document.querySelector<HTMLInputElement>(".disc-value")?.focus(); return; }
    if (payTooMuch) { document.getElementById("pay-now")?.focus(); return; }
    saving = true;
    const body = {
      patient_id: patient?.id ?? null,
      patient: newPatient ? { ...newPatient, age_years: Number(newPatient.age_years), gender: newPatient.gender || "other" } : null,
      referring_doctor_id: doctor && doctor.name === doctorText ? doctor.id : null,
      referring_doctor_name: doctor && doctor.name === doctorText ? "" : doctorText,
      lines: lines.map((l) => ({ test_id: l.test.id, quantity: l.quantity })),
      discount_type: discountType, discount_value: discountType === "none" ? "0" : String(Number(discountValue) || 0),
      payments: paying > 0 ? [{ mode: payMode, amount: paying.toFixed(2), reference: payRef }] : [],
      notes, hold,
    };
    if (!connection.usable) { await saveOffline(print, body, newPatient); return; }
    try {
      const bill = await post<Bill>("/api/bills", body, { "Idempotency-Key": requestKey });
      finished = true;
      clearDraft(DRAFT);
      setBeforeLeave(null);
      notify(`${bill.invoice_no} for ${bill.patient_name}: ${rupees(bill.total)}${Number(bill.due) > 0 ? `, ${rupees(bill.due)} due` : ", fully paid"}.`, { title: "Bill saved" });
      if (print) window.open(`/bills/${bill.id}/print`, "_blank", "noopener");
      navigate(`/bills/${bill.id}`, { replace: true });
    } catch (e) {
      // CIDMS couldn't be reached: keep the bill on this computer instead (same key, so if the save did get
      // through, sending it later finds that bill instead of making another).
      if (e instanceof ApiError && e.transient) { await saveOffline(print, body, newPatient); return; }
      requestKey = newRequestKey();
      if (e instanceof ApiError && Object.keys(e.fieldErrors).length) {
        const own: Record<string, string> = {}, theirs: Record<string, string> = {};
        for (const [k, v] of Object.entries(e.fieldErrors)) {
          if (k.startsWith("patient.")) theirs[k.slice(8)] = v; else own[k] = v;
        }
        if (Object.keys(theirs).length) { np.errors = theirs; np.submitted = true; }
        errors = own;
        notifyError(e, { title: "Check the bill" });
      } else notifyError(e, { title: "Couldn't save the bill" });
    } finally {
      saving = false;
    }
  }

  async function saveOffline(print: boolean, body: Record<string, unknown>, newPatient: z.output<typeof patientSchema> | null) {
    saving = true;
    try {
      const now = new Date().toISOString();
      const who = session.me?.full_name ?? "";
      const p = patient ?? null;
      const record = await saveOfflineBill(requestKey, body, {
        legacy_no: null, patient_id: p?.id ?? "", patient_name: (p?.name ?? newPatient?.name ?? "").replace(/\s+/g, " ").trim(),
        patient_mobile: p?.mobile ?? newPatient?.mobile ?? "", patient_age: `${p?.age_years ?? newPatient?.age_years ?? ""} Y`,
        patient_gender: p?.gender ?? newPatient?.gender ?? "other", patient_address: p?.address ?? newPatient?.address ?? "",
        guardian_name: p?.guardian_name ?? newPatient?.guardian_name ?? "",
        referring_doctor_id: doctor && doctor.name === doctorText ? doctor.id : null, referring_doctor_name: doctorText.trim(),
        status: hold ? "on_hold" : "confirmed", subtotal: subtotal.toFixed(2), discount_type: discountType,
        discount_value: discountType === "none" ? "0" : String(Number(discountValue) || 0), discount_amount: discount.toFixed(2),
        total: total.toFixed(2), paid: paying.toFixed(2), due: dueAfter.toFixed(2), notes, cancel_reason: "", created_by_name: who,
        items: lines.map((l, i) => ({
          id: `line-${i + 1}`, position: i + 1, test_id: l.test.id, test_name: l.test.name, department_name: l.test.department.name,
          is_imaging: !!l.test.test_type?.is_imaging, unit_price: Number(l.test.price).toFixed(2), quantity: l.quantity,
          amount: (Number(l.test.price) * l.quantity).toFixed(2), status: "billed" as const, accession_no: "", status_changed_at: null,
        })),
        payments: paying > 0 ? [{ id: "pay-1", kind: "payment" as const, amount: paying.toFixed(2), mode: payMode, reference: payRef, note: "",
                                  received_at: now, received_by_name: who }] : [],
      }, p?.patient_no ?? "");
      finished = true;
      clearDraft(DRAFT);
      setBeforeLeave(null);
      notify(`Kept on this computer as ${record.offline_no}. It goes to CIDMS by itself when the connection is back, and gets its bill number then.`,
             { title: "Bill saved offline", kind: "warning" });
      if (print) window.open(`/bills/offline/${record.id}/print`, "_blank", "noopener");
      navigate(`/bills/offline?made=${record.id}`, { replace: true });
    } catch (e) {
      notifyError(e, { title: "Couldn't keep the bill on this computer" });
    } finally {
      saving = false;
    }
  }

  function onKeys(e: KeyboardEvent) {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); save(false); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "p") { e.preventDefault(); save(true); }
  }
</script>

<svelte:window onkeydown={onKeys} />

{#snippet testCell(l: Line)}<div class="cell-title">{l.test.name}</div><div class="cell-sub">{l.test.department.name}</div>{/snippet}
{#snippet qtyCell(l: Line)}
  <input class="input tabular qty" type="number" min="1" max="20" inputmode="numeric" aria-label="Quantity of {l.test.name}" value={l.quantity}
         aria-invalid={!!qtyProblems[l.test.id]} onchange={(e) => setQty(l.test.id, e.currentTarget.valueAsNumber)} />
{/snippet}
{#snippet lineTotal(l: Line)}<span class="money font-semibold">{rupees(Number(l.test.price) * l.quantity)}</span>{/snippet}

<PageHeader eyebrow="Front desk" title="New bill" description="Find the patient, add the tests, take the payment. Prices come from your catalogue.">
  {#snippet actions()}
    {#if dirty}<span class="draft-saved text-sm text-muted" role="status"><Icon name="check" size="sm" />Draft saved on this computer</span>
      <Button variant="ghost-destructive" size="sm" icon="trash" onclick={clearTheDraft} tooltip="Empty the form and remove the draft">Clear draft</Button>{/if}
    <span class="text-sm text-muted hide-sm"><span class="kbd">Ctrl</span> + <span class="kbd">Enter</span> saves · <span class="kbd">Ctrl</span> + <span class="kbd">P</span> saves and prints</span>{/snippet}
</PageHeader>

{#if !connection.usable}
  <div class="alert alert-warning draft-note" role="status"><Icon name="alert" />
    <div class="grow"><div class="alert-title">You're offline: billing carries on</div>
      {#if offline.readyAt}Bills are kept on this computer with a provisional number and printed; they go to CIDMS by themselves when the connection is back.
        Tests, prices and doctors are as of {new Date(offline.readyAt).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}; existing patients are the {300} most recent.
      {:else}This computer has no copy of the tests and prices yet. Open CIDMS once while online, and it can bill offline from then on.{/if}</div>
  </div>
{/if}
{#if restored}
  <div class="alert alert-info draft-note" role="status"><Icon name="info" />
    <div class="grow"><div class="alert-title">Your unsaved bill is back</div>From {savedAgo(restored.saved_at)}. It's kept on this computer until you save it.</div>
    <Button variant="ghost" size="sm" onclick={() => (restored = null)}>OK</Button>
    <Button variant="outline" size="sm" icon="trash" onclick={clearTheDraft}>Clear draft</Button>
  </div>
{:else if waiting}
  <div class="alert alert-warning draft-note" role="status"><Icon name="alert" />
    <div class="grow"><div class="alert-title">You have an unsaved bill</div>Started {savedAgo(waiting.saved_at)}{waiting.value.patient ? ` for ${waiting.value.patient.name}` : ""}. Open it, or carry on with this one (the unsaved bill is kept).</div>
    <Button variant="outline" size="sm" onclick={openWaiting}>Open the unsaved bill</Button>
  </div>
{/if}

<div class="nb-grid">
  <div class="stack nb-main">
    <section class="card" aria-labelledby="p-title">
      <div class="card-header"><div><h2 class="card-title" id="p-title">Patient</h2>
        <p class="card-description">Search by name, mobile or patient number, or add someone new.</p></div></div>
      <div class="card-content stack">
        {#if patient}
          <div class="picked">
            <span class="avatar" aria-hidden="true">{patient.name.charAt(0)}</span>
            <div class="grow">
              <div class="font-semibold">{patient.name} <span class="badge badge-navy badge-plain mono">{patient.patient_no}</span></div>
              <div class="text-sm text-muted">{[patient.age_years !== null ? `${patient.age_years} Y` : "", patient.gender, formatPhone(patient.mobile), patient.guardian_name ? `C/O ${patient.guardian_name}` : ""].filter(Boolean).join(" · ")}</div>
            </div>
            <Button variant="ghost" size="sm" onclick={() => { patient = null; patientQuery = ""; }}>Change</Button>
          </div>
        {:else if !addingPatient}
          <Combobox id="patient-search" label="Find a patient" placeholder="Name, mobile or patient number…" searchPage={searchPatients} bind:value={patientQuery}
                    onpick={(p) => { patient = p; patientQuery = ""; }} onadd={startNewPatient} addLabel="a new patient" autofocus emptyText="No patient found.">
            {#snippet option(p)}
              <div class="row-between"><span><span class="font-semibold">{p.name}</span> <span class="text-xs text-muted mono">{p.patient_no}</span></span>
                <span class="text-sm text-muted tabular">{formatPhone(p.mobile) || "—"}</span></div>
              <div class="text-xs text-muted">{[p.age_years !== null ? `${p.age_years} Y` : "", p.gender, p.guardian_name ? `C/O ${p.guardian_name}` : "", p.address].filter(Boolean).join(" · ")}</div>
            {/snippet}
          </Combobox>
          <div><Button size="sm" icon="plus" onclick={startNewPatient}>New patient</Button></div>
          {#if errors.patient}<p class="field-error"><Icon name="alert" size="sm" />{errors.patient}</p>{/if}
        {:else}
          <FormErrors form={np} labels={patientLabels} idPrefix="np-" />
          <div class="form-grid">
            <Field id="np-name" label="Full name" required error={np.error("name")}>
              {#snippet children({ invalid, describedby })}<input id="np-name" class="input" autocomplete="off" bind:value={np.values.name} {...np.field("name")} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
            </Field>
            <Field id="np-mobile" label="Mobile" optional error={np.error("mobile")}
                   tip="Others already registered with this number are shown, so a family member isn't added twice. Bills and reports can be sent here.">
              {#snippet children({ invalid, describedby })}
                {@const f = np.field("mobile")}
                <PhoneInput id="np-mobile" bind:value={np.values.mobile} {invalid} {describedby} onblur={f.onblur} oninput={onMobile} />
              {/snippet}
            </Field>
          </div>
          {#if family.length}
            <div class="alert alert-info"><Icon name="info" /><div><div class="alert-title">Already registered with this mobile</div>
              <div class="row-wrap family">
                {#each family as f (f.id)}<Button size="sm" onclick={() => { patient = f; addingPatient = false; }}>{f.name} · {f.age_years ?? "?"} Y</Button>{/each}
              </div><div class="text-xs family-note">Pick one if it's the same person, or carry on for a family member.</div></div></div>
          {/if}
          <div class="form-grid three">
            <Field id="np-age_years" label="Age (years)" required error={np.error("age_years")}
                   tip="In completed years; 0 for a baby under one. The date of birth can be added later on the patient's page, and the age is then worked out from it.">
              {#snippet children({ invalid, describedby })}<input id="np-age_years" class="input tabular" type="number" min="0" max="130" inputmode="numeric" bind:value={np.values.age_years} {...np.field("age_years")} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
            </Field>
            <Field id="np-gender" label="Gender" required error={np.error("gender")}>
              {#snippet children({ invalid, describedby })}
                <select id="np-gender" class="select" bind:value={np.values.gender} {...np.field("gender")} aria-invalid={invalid} aria-describedby={describedby}>
                  <option value="" disabled>Choose…</option><option value="female">Female</option><option value="male">Male</option><option value="other">Other</option>
                </select>
              {/snippet}
            </Field>
            <Field id="np-guardian_name" label="Guardian (C/O)" optional error={np.error("guardian_name")} tip="Father, husband or whoever the patient comes with. Printed on the bill as C/O.">
              {#snippet children({ invalid, describedby })}<input id="np-guardian_name" class="input" bind:value={np.values.guardian_name} {...np.field("guardian_name")} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
            </Field>
          </div>
          <Field id="np-address" label="Address" optional error={np.error("address")}>
            {#snippet children({ invalid, describedby })}<input id="np-address" class="input" bind:value={np.values.address} {...np.field("address")} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
          </Field>
          <div><button class="link-button" type="button" onclick={() => (addingPatient = false)}>Search existing patients instead</button></div>
        {/if}
      </div>
    </section>

    <section class="card" aria-labelledby="d-title">
      <div class="card-header"><div><h2 class="card-title" id="d-title">Referred by
        <InfoTip about="Referred by" text="The doctor or hospital that sent the patient. It prints on the bill as Consultant, and the referral reports count bills by referrer. Leave it empty when the patient came on their own (Self)." /></h2>
        <p class="card-description">Choose a doctor or hospital from your list, add a new one, or leave it as self.</p></div></div>
      <div class="card-content stack">
        {#if doctor && doctor.name === doctorText}
          <div class="picked">
            <span class="avatar" aria-hidden="true"><Icon name="stethoscope" size="sm" /></span>
            <div class="grow">
              <div class="font-semibold">{doctor.name}</div>
              <div class="text-sm text-muted">{[doctor.qualification, formatPhone(doctor.phone)].filter(Boolean).join(" · ") || "Referred by"}</div>
            </div>
            <Button variant="ghost" size="sm" onclick={() => { doctor = null; doctorText = ""; }}>Change</Button>
          </div>
        {:else}
          <Combobox id="doctor" label="Find a doctor or hospital" placeholder="Name, degree or phone… (leave empty for Self)" icon="stethoscope" searchPage={searchDoctors}
                    bind:value={doctorText} onpick={(d) => { doctor = d; doctorText = d.name; }}
                    onadd={startNewDoctor} addLabel="a new doctor or hospital" emptyText="Not in your list yet.">
            {#snippet option(d)}
              <div class="row-between"><span class="font-semibold">{d.name}</span>
                <span class="text-sm text-muted tabular">{formatPhone(d.phone) || "—"}</span></div>
              {#if d.qualification}<div class="text-xs text-muted">{d.qualification}</div>{/if}
            {/snippet}
          </Combobox>
          <div class="row-wrap">
            <Button size="sm" icon="plus" onclick={startNewDoctor}>New doctor / hospital</Button>
            {#if doctorText}<Button variant="ghost" size="sm" onclick={() => { doctorText = ""; doctor = null; }} tooltip="No referring doctor or hospital: the patient came on their own">Self</Button>{/if}
          </div>
        {/if}
      </div>
    </section>

    <section class="card" aria-labelledby="t-title">
      <div class="card-header"><div><h2 class="card-title" id="t-title">Tests</h2>
        <p class="card-description">Tick the tests in the list: each one goes straight onto the bill.</p></div>
        {#if lines.length}<span class="badge badge-info badge-plain">{lines.length} on the bill</span>{/if}</div>
      <div class="card-content stack">
        <div class="test-row">
          <div class="field">
            <div class="label-row"><label class="label" for="nb-test">Test name</label>
              <InfoTip about="Test name" text="Type part of the name or the short code. Tick as many as needed; the list stays open. Only active tests are listed, at today's price." /></div>
            <TestSelect id="nb-test" selected={onBill} ontoggle={toggleTest} />
          </div>
          <div class="field">
            <label class="label" for="nb-rate">Total price (₹)</label>
            <input id="nb-rate" class="input money" value={subtotal.toFixed(2)} readonly />
          </div>
        </div>
        {#if errors.lines}<p class="field-error"><Icon name="alert" size="sm" />{errors.lines}</p>{/if}
        {#each Object.entries(qtyProblems) as [id, message] (id)}<p class="field-error" role="alert"><Icon name="alert" size="sm" />{message}</p>{/each}
      </div>
      <DataTable label="Tests on the bill" rows={lines} rowKey={(l) => l.test.id}
                 actionsInline minWidth={0}
                 actions={(l) => [{ label: `Remove ${l.test.name}`, icon: "trash", tone: "danger", onclick: () => toggleTest(l.test, false) }]}
                 actionsLabel={(l) => `Actions for ${l.test.name}`}
                 empty={{ icon: "flask", title: "No tests added yet.", text: "Use the box above to find and tick tests." }}
                 columns={[
                   { key: "test", label: "Test name", cell: testCell, mobile: "title", width: "44%" },
                   { key: "qty", label: "Qty", cell: qtyCell, align: "right", width: "12%" },
                   { key: "unit", label: "Unit price", value: (l) => rupees(l.test.price), align: "right", class: "money", width: "15%" },
                   { key: "total", label: "Total price", cell: lineTotal, align: "right", mobile: "end", width: "17%" },
                 ]} />
    </section>

    <section class="card">
      <div class="card-content">
        <Field id="notes" label="Notes on the bill" optional hint="Printed on the bill.">
          {#snippet children({ describedby })}<textarea id="notes" class="textarea notes" bind:value={notes} aria-describedby={describedby}></textarea>{/snippet}
        </Field>
      </div>
    </section>
  </div>

  <aside class="card summary" aria-labelledby="s-title" id="bill-summary">
    <div class="card-header"><h2 class="card-title" id="s-title">Summary</h2><span class="text-sm text-muted">{lines.length} {lines.length === 1 ? "test" : "tests"}</span></div>
    <div class="card-content stack" class:is-waiting={noTests}>
      {#if noTests}<p class="waiting-note text-sm"><Icon name="info" size="sm" />Add a test to continue.</p>{/if}
      <div class="line"><span class="text-muted">Subtotal</span><span class="money">{rupees(subtotal)}</span></div>
      <div class="field">
        <div class="label-row"><span class="label" id="disc-label">Discount</span><InfoTip about="Discount" text={discountTip} /></div>
        <div class="row" role="group" aria-labelledby="disc-label">
          <div class="disc-kind" role="radiogroup" aria-label="Discount in">
            <label class:is-on={discountKind === "percent"}><input type="radio" name="disc-kind" value="percent" bind:group={discountKind} disabled={noTests} /> %<span class="sr-only"> Percent</span></label>
            <label class:is-on={discountKind === "amount"}><input type="radio" name="disc-kind" value="amount" bind:group={discountKind} disabled={noTests} /> ₹<span class="sr-only"> Rupees</span></label>
          </div>
          <input class="input money disc-value" type="number" min="0" step={discountKind === "percent" ? "1" : "0.01"} max={discountKind === "percent" ? 100 : subtotal}
                 inputmode="decimal" placeholder={discountKind === "percent" ? "0 %" : "₹ 0"}
                 aria-label={discountKind === "percent" ? "Discount percent" : "Discount in rupees"} bind:value={discountValue} aria-invalid={!!errors.discount_value || !!discountProblem}
                 disabled={noTests} />
        </div>
        {#if overLimit && !overLimitOk}<p class="field-error"><Icon name="alert" size="sm" />Above the centre's {maxDiscount}% limit: the owner must approve it.</p>{/if}
        {#if discountProblem}<p class="field-error" role="alert"><Icon name="alert" size="sm" />{discountProblem}</p>
        {:else if errors.discount_value}<p class="field-error"><Icon name="alert" size="sm" />{errors.discount_value}</p>{/if}
      </div>
      {#if discount > 0}<div class="line"><span class="text-muted">Discount</span><span class="money">− {rupees(discount)}</span></div>{/if}
      <div class="line grand"><span>Total</span><span class="money">{rupees(total)}</span></div>

      <hr class="divider" />
      <div class="field">
        <div class="row-between"><div class="label-row"><label class="label" for="pay-now">Paid now (₹)</label>
          <InfoTip about="Paid now" text="What the patient pays at the desk now. Leave it empty if nothing is paid; the rest stays due and can be collected later from Dues, in as many instalments as needed." /></div>
          {#if total > 0}<button class="link-button" type="button" disabled={noTests} onclick={() => (payNow = total.toFixed(2))}>Full amount</button>{/if}</div>
        <div class="row pay-row">
          <input id="pay-now" class="input money" type="number" min="0" step="0.01" max={total} inputmode="decimal" placeholder="0" bind:value={payNow} disabled={noTests}
                 aria-invalid={payTooMuch} aria-describedby={payTooMuch ? "pay-capped" : undefined} />
          <label class="sr-only" for="pay-mode">Paid by</label>
          <select id="pay-mode" class="select pay-mode" bind:value={payMode} disabled={noTests}>{#each PAYMENT_MODES as [v, l] (v)}<option value={v}>{l}</option>{/each}</select>
          <InfoTip about="Paid by" text="How the money was taken. The day's collection is split by this (cash in the drawer, UPI, card…). Add the UPI or card reference so it can be matched with the bank." />
        </div>
        {#if payTooMuch}<p class="field-error" id="pay-capped" role="alert"><Icon name="alert" size="sm" />Paid now can't be more than the total, {rupees(total)}.</p>{/if}
        {#if payMode !== "cash" && paying > 0}<input class="input mono" placeholder="UPI / card reference" aria-label="Payment reference" bind:value={payRef} disabled={noTests} />{/if}
      </div>
      <div class="line {dueAfter > 0 ? 'is-due' : ''}"><span>{dueAfter > 0 ? "Due after this" : "Nothing due"}</span><span class="money">{rupees(dueAfter)}</span></div>
      <div class="check-line"><label class="check-row"><input class="checkbox" type="checkbox" bind:checked={hold} disabled={noTests} /> Put the bill on hold</label>
        <InfoTip about="On hold" text="Saves the bill without sending its tests to the worklist, e.g. while waiting for the doctor's slip. Confirm it later from the bill." /></div>
    </div>
    <div class="card-footer card-footer-stack summary-actions">
      <Button variant="primary" size="lg" block icon="printer" loading={saving || np.submitting} loadingText="Saving…" disabled={noTests}
              tooltip={noTests ? "Add a test first" : ""} onclick={() => save(true)}>Save and print</Button>
      <Button block icon="check" disabled={saving || np.submitting || noTests} tooltip={noTests ? "Add a test first" : ""} onclick={() => save(false)}>Save bill</Button>
    </div>
  </aside>
</div>

<!-- Phones and tablets: the total and Save stay at the bottom of the screen. -->
<div class="savebar" role="region" aria-label="Bill total and save">
  <a class="savebar-total" href="#bill-summary">
    <span class="text-xs text-muted">Total · {lines.length} {lines.length === 1 ? "test" : "tests"}</span>
    <strong class="money">{rupees(total)}</strong>
    {#if dueAfter > 0 && lines.length}<span class="text-xs money-due">{rupees(dueAfter)} due</span>{/if}
  </a>
  <Button disabled={saving || np.submitting || noTests} onclick={() => save(false)} aria-label="Save bill">Save</Button>
  <Button variant="primary" icon="printer" loading={saving || np.submitting} disabled={noTests} onclick={() => save(true)} aria-label="Save and print">Save & print</Button>
</div>
<div class="savebar-space" aria-hidden="true"></div>

<FormDialog bind:open={addingDoctor} title="Add a referring doctor or hospital" icon="stethoscope" tone="info"
            description="Added to your list of doctors and hospitals and chosen for this bill."
            submitLabel="Add" submitIcon="check" busy={doctorForm.submitting} busyLabel="Adding…"
            onsubmit={submitting(doctorForm, "Couldn't add it")}>
    <FormErrors form={doctorForm} labels={{ name: "Name", qualification: "Qualification", phone: "Phone" }} idPrefix="nd-" />
    <Field id="nd-name" label="Doctor or hospital name" required error={doctorForm.error("name")} tip="As it should print on the bill, e.g. Dr. Kakali Sarkar or City Nursing Home.">
      {#snippet children({ invalid, describedby })}<input id="nd-name" class="input" autocomplete="off" placeholder="e.g. Dr. Kakali Sarkar or City Nursing Home" bind:value={doctorForm.values.name} {...doctorForm.field("name")} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
    </Field>
    <div class="form-grid">
      <Field id="nd-qualification" label="Qualification" optional tip="For a doctor, e.g. MBBS, MD. Leave empty for a hospital." error={doctorForm.error("qualification")}>
        {#snippet children({ invalid, describedby })}<input id="nd-qualification" class="input" placeholder="e.g. MBBS, MD" bind:value={doctorForm.values.qualification} {...doctorForm.field("qualification")} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
      </Field>
      <Field id="nd-phone" label="Phone" optional error={doctorForm.error("phone")}>
        {#snippet children({ invalid, describedby })}
          {@const f = doctorForm.field("phone")}
          <PhoneInput id="nd-phone" bind:value={doctorForm.values.phone} {invalid} {describedby} onblur={f.onblur} oninput={f.oninput} />
        {/snippet}
      </Field>
    </div>
</FormDialog>

<style>
  .nb-grid { display: grid; grid-template-columns: minmax(0, 9fr) minmax(280px, 1fr); gap: 16px; align-items: start; }
  .nb-main { min-width: 0; }
  .picked { display: flex; align-items: center; gap: 12px; min-width: 0; padding: 12px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--muted); }
  .summary { position: sticky; top: calc(var(--topbar-height) + 16px); }
  .line { display: flex; justify-content: space-between; gap: 12px; font-size: 14px; }
  .line.grand { font-size: 20px; font-weight: 700; font-family: var(--font-heading); }
  .line.is-due { color: var(--destructive); font-weight: 600; }
  .test-row { display: grid; grid-template-columns: minmax(0, 1fr) 180px; gap: 12px; align-items: end; }
  .form-grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  /* A label's ⓘ tip wrapping onto its own line (some fields have one, some don't) is what was throwing the
     boxes below out of line across a row; keeping every label on one line keeps them level. */
  .form-grid :global(.label-row) { flex-wrap: nowrap; }
  .family, .family-note { margin-top: 6px; }
  .notes { min-height: 64px; }
  .disc-kind { display: inline-flex; flex: none; height: 38px; padding: 3px; gap: 2px; border: 1px solid var(--input); border-radius: 9px; background: var(--background); }
  .disc-kind label { display: inline-flex; align-items: center; gap: 4px; padding: 0 10px; border-radius: 6px; font-size: 13px; font-weight: 500; cursor: pointer; white-space: nowrap; }
  .disc-kind label:hover { background: var(--muted); }
  .disc-kind label.is-on { background: var(--primary); color: #fff; }
  .disc-kind input { position: absolute; opacity: 0; width: 1px; height: 1px; }
  .disc-kind label:has(input:focus-visible) { box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 25%, transparent); }
  .disc-value { flex: 1 1 0; min-width: 0; }
  .pay-row { gap: 8px; }
  .pay-row .money { flex: 1 1 0; min-width: 0; }
  .pay-mode { flex: none; width: 96px; }
  .qty { width: 72px; margin-left: auto; text-align: right; }
  .savebar, .savebar-space { display: none; }
  @media (max-width: 900px) {
    .nb-grid { grid-template-columns: minmax(0, 1fr); }
    .summary { position: static; }
    .summary-actions { display: none; }
    .savebar { position: fixed; left: 0; right: 0; bottom: 0; z-index: 30; display: flex; align-items: center; gap: 8px;
      padding: 10px max(12px, env(safe-area-inset-right)) calc(10px + env(safe-area-inset-bottom)) max(12px, env(safe-area-inset-left));
      background: color-mix(in srgb, var(--card) 94%, transparent); backdrop-filter: blur(8px); border-top: 1px solid var(--border);
      box-shadow: 0 -6px 20px rgb(15 23 42 / .08); }
    .savebar-space { display: block; height: calc(72px + env(safe-area-inset-bottom)); }
    .savebar-total { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; line-height: 1.2; color: inherit; text-decoration: none !important; }
    .savebar-total strong { font-size: 18px; }
    .savebar :global(.btn) { height: 44px; flex: none; }
  }
  @media (max-width: 640px) {
    .test-row { grid-template-columns: 1fr; }
    .form-grid.three { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .form-grid.three > :global(:last-child) { grid-column: 1 / -1; }
    .qty { margin-left: 0; width: 84px; }
  }
  @media (max-width: 380px) {
    .savebar :global(.btn-outline) { padding: 0 12px; }
  }
  .draft-note { margin-bottom: 16px; align-items: center; }
  @media (max-width: 600px) { .draft-note { flex-wrap: wrap; } }
  /* Until a test is added the summary's controls are switched off (the help buttons still work). */
  .is-waiting .disc-kind label, .is-waiting .check-row { opacity: .55; cursor: not-allowed; }
  .is-waiting .link-button:disabled { opacity: .5; cursor: not-allowed; text-decoration: none; }
  .waiting-note { display: flex; align-items: flex-start; gap: 6px; margin: 0; padding: 8px 10px; border-radius: 8px;
    background: var(--muted); color: var(--muted-foreground); }
  .waiting-note :global(.icon) { flex: none; margin-top: 2px; }
  .field-hint { display: flex; align-items: center; gap: 5px; margin: 6px 0 0; font-size: 12.5px; color: var(--primary-text); }
  .draft-saved { display: inline-flex; align-items: center; gap: 5px; }
</style>
