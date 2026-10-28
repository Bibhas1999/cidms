<script lang="ts">
  import { z } from "zod";
  import Button from "../../components/Button.svelte";
  import Combobox from "../../components/Combobox.svelte";
  import DataTable from "../../components/DataTable.svelte";
  import Field from "../../components/Field.svelte";
  import FormDialog from "../../components/FormDialog.svelte";
  import FormErrors from "../../components/FormErrors.svelte";
  import Icon from "../../components/Icon.svelte";
  import InfoTip from "../../components/InfoTip.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import PhoneInput from "../../components/PhoneInput.svelte";
  import StatusBadge from "../../components/StatusBadge.svelte";
  import type { RowAction } from "../../components/RowMenu.svelte";
  import { ApiError, get, newRequestKey, post } from "../../lib/api";
  import { PAYMENT_MODES, type Patient, type PaymentMode } from "../../lib/bill-types";
  import { Form } from "../../lib/form.svelte";
  import { date as fmtDate, rupees } from "../../lib/format";
  import { formatPhone, splitPhone } from "../../lib/phone";
  import { router, setQuery } from "../../lib/router.svelte";
  import { optionalText, personName, phone, submitting, text, wholeNumber } from "../../lib/schemas";
  import { session } from "../../lib/session.svelte";
  import { notify, notifyError } from "../../lib/toast.svelte";
  import { tooltip } from "../../lib/tooltip";
  import { ageGender, GENDER_LABELS, type OpdDoctor, type OpdVisit, type Page, type VisitStatus } from "../../lib/types";

  // The OPD desk: the day's visits for each doctor in token order. A new visit takes the consultation fee (a bill
  // is made when there's a fee) and gives the next token for that doctor; then each patient is called in and done.
  // Refreshes every 20 seconds while the tab is in view, so two desks see the same queue.

  const REFRESH_MS = 20_000;
  const istToday = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
  const timeOf = (iso: string | null) =>
    iso ? new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "numeric", minute: "2-digit" }).format(new Date(iso)) : "";

  const STATUS: Record<VisitStatus, { tone: "info" | "warning" | "success" | "destructive"; label: string }> = {
    waiting: { tone: "info", label: "Waiting" },
    with_doctor: { tone: "warning", label: "With doctor" },
    done: { tone: "success", label: "Done" },
    cancelled: { tone: "destructive", label: "Cancelled" },
  };

  const today = istToday();
  const day = $derived(router.query.get("date") || today);
  const isToday = $derived(day === today);
  const doctorId = $derived(router.query.get("doctor") ?? "");
  const statusFilter = $derived((router.query.get("status") ?? "") as VisitStatus | "");
  const canManage = $derived(session.can("appointments.manage"));

  let visits = $state<OpdVisit[] | null>(null);
  let doctors = $state<OpdDoctor[]>([]);
  let loadError = $state("");
  let loading = $state(false);
  let reload = $state(0);
  let quiet = false; // a background refresh: no loading shimmer
  let busy = $state<string | null>(null);

  $effect(() => {
    const ctrl = new AbortController();
    const query = { date: day };
    reload;
    loading = !quiet;
    quiet = false;
    get<OpdVisit[]>("/api/opd/visits", query, ctrl.signal)
      .then((v) => { visits = v; loadError = ""; })
      .catch((e) => { if (e.name !== "AbortError") loadError = e.message; })
      .finally(() => { loading = false; });
    return () => ctrl.abort();
  });

  $effect(() => {
    get<OpdDoctor[]>("/api/opd/doctors").then((d) => (doctors = d)).catch((e) => notifyError(e, { title: "Couldn't load the OPD doctors" }));
  });

  // Every 20 s while the tab is in view (and at once when it comes back into view); only today's queue moves.
  $effect(() => {
    if (!isToday) return;
    const tick = () => { if (document.visibilityState === "visible" && !busy) { quiet = true; reload++; } };
    const timer = setInterval(tick, REFRESH_MS);
    document.addEventListener("visibilitychange", tick);
    return () => { clearInterval(timer); document.removeEventListener("visibilitychange", tick); };
  });

  // One tab per doctor: the active doctors, and any other doctor with visits that day.
  const tabs = $derived.by(() => {
    const list = doctors.filter((d) => d.is_active).map((d) => ({ id: d.id, name: d.name }));
    for (const v of visits ?? []) if (!list.some((d) => d.id === v.doctor.id)) list.push({ id: v.doctor.id, name: v.doctor.name });
    return list.map((d) => ({ ...d, waiting: (visits ?? []).filter((v) => v.doctor.id === d.id && v.status === "waiting").length }));
  });
  const ofDoctor = $derived((visits ?? []).filter((v) => !doctorId || v.doctor.id === doctorId));
  const rows = $derived(ofDoctor.filter((v) => !statusFilter || v.status === statusFilter));
  const counts = $derived(Object.fromEntries((Object.keys(STATUS) as VisitStatus[]).map((s) => [s, ofDoctor.filter((v) => v.status === s).length])) as Record<VisitStatus, number>);
  const nowWith = $derived(doctorId ? ofDoctor.find((v) => v.status === "with_doctor") ?? null : null);
  const allWaiting = $derived((visits ?? []).filter((v) => v.status === "waiting").length);

  // ---------- moving a visit along ----------
  async function setStatus(v: OpdVisit, status: VisitStatus, message: string, reason = "") {
    busy = v.id;
    try {
      await post(`/api/opd/visits/${v.id}/status`, reason ? { status, reason } : { status });
      notify(message);
      reload++;
    } catch (e) {
      notifyError(e, { title: "Couldn't update the visit" });
      reload++;
    } finally {
      busy = null;
    }
  }
  const who = (v: OpdVisit) => `Token ${v.token_no}, ${v.patient.name}`;
  const callIn = (v: OpdVisit) => setStatus(v, "with_doctor", `${who(v)}: called in to ${v.doctor.name}.`);
  const finish = (v: OpdVisit) => setStatus(v, "done", `${who(v)}: done.`);
  function undo(v: OpdVisit) {
    if (v.status === "with_doctor") void setStatus(v, "waiting", `${who(v)} is back in the queue.`);
    else if (v.status === "done") void setStatus(v, "with_doctor", `${who(v)} is back with ${v.doctor.name}.`);
  }

  // ---------- cancel (with a reason) ----------
  let cancelOpen = $state(false);
  let cancelling = $state<OpdVisit | null>(null);
  const cancelForm = new Form({
    schema: z.object({ reason: text("Give a reason of at least 3 characters.", 300, 3) }),
    initial: { reason: "" },
    onSubmit: async ({ reason }) => {
      const v = cancelling!;
      await post(`/api/opd/visits/${v.id}/status`, { status: "cancelled", reason });
      notify(`${who(v)}: visit cancelled.${Number(v.paid) > 0 ? " The fee bill is left as it is; refund it from the bill if needed." : ""}`);
      cancelOpen = false;
      reload++;
    },
  });
  function openCancel(v: OpdVisit) {
    cancelling = v;
    cancelForm.reset();
    cancelOpen = true;
  }

  function actionsFor(v: OpdVisit): RowAction[] {
    const out: RowAction[] = [];
    if (canManage && (v.status === "with_doctor" || v.status === "done"))
      out.push({ label: "Undo", icon: "refresh", onclick: () => undo(v), hint: v.status === "done" ? "Back to With doctor" : "Back to Waiting" });
    if (v.invoice_id) out.push({ label: "Open the fee bill", icon: "receipt", href: `/bills/${v.invoice_id}`, hint: v.invoice_no ?? "" });
    out.push({ label: "Patient's page", icon: "user", href: `/patients/${v.patient.id}` });
    if (canManage && (v.status === "waiting" || v.status === "with_doctor"))
      out.push({ label: "Cancel visit", icon: "x", tone: "danger", onclick: () => openCancel(v), hint: "Asks for a reason; the fee bill stays" });
    return out;
  }

  // ---------- new visit ----------
  let newOpen = $state(false);
  let picked = $state<Patient | null>(null);
  let adding = $state(false);
  let patientQuery = $state("");
  let family = $state<Patient[]>([]);
  let requestKey = newRequestKey();

  const patientSchema = z.object({
    name: personName("Enter the patient's name."),
    mobile: phone(false),
    age_years: wholeNumber({ min: 0, max: 130, required: "Enter the age in years.", label: "the age in years" }),
    gender: z.string().refine((v) => v in GENDER_LABELS, "Choose the gender."),
  });
  const visitSchema = z.object({
    name: z.string(), mobile: z.string(), age_years: z.any(), gender: z.string(),
    doctor_id: z.string().min(1, "Choose the doctor."),
    fee: z.any(),
    pay_now: z.any(),
    pay_mode: z.string(),
    reference: optionalText(100),
  });
  const labels = { patient: "Patient", name: "Full name", mobile: "Mobile", age_years: "Age", gender: "Gender", doctor_id: "Doctor",
                   fee: "Fee", pay_now: "Paid now", pay_mode: "Paid by", reference: "Reference" };
  const blank = { name: "", mobile: "", age_years: null as number | null, gender: "", doctor_id: "", fee: null as number | string | null,
                  pay_now: null as number | string | null, pay_mode: "cash" as PaymentMode, reference: "" };

  const round2 = (n: number) => Math.round(n * 100) / 100;
  const empty = (v: unknown) => v === null || v === undefined || v === "";
  /** The fee's problem, if any (empty, below 0, more than two decimals). */
  function feeProblem(v: unknown): string {
    if (empty(v)) return "Enter the fee, or 0 for no fee.";
    const n = Number(v);
    if (!Number.isFinite(n) || n < 0) return "Enter a fee of 0 or more.";
    if (Math.abs(Math.round(n * 100) - n * 100) > 1e-6) return "Use at most two decimal places (paise).";
    return "";
  }
  /** Paid now: empty is nothing paid; more than the fee is an error shown at once (not only after leaving the box). */
  function payProblem(pay: unknown, fee: unknown): string {
    if (empty(pay)) return "";
    const n = Number(pay);
    if (!Number.isFinite(n) || n < 0) return "Enter an amount of 0 or more.";
    if (Math.abs(Math.round(n * 100) - n * 100) > 1e-6) return "Use at most two decimal places (paise).";
    if (!feeProblem(fee) && round2(n) > round2(Number(fee))) return `Paid now can't be more than the fee, ${rupees(Number(fee))}.`;
    return "";
  }

  const visit = new Form({
    schema: visitSchema, initial: blank,
    serverFields: { "patient.name": "name", "patient.mobile": "mobile", "patient.age_years": "age_years", "patient.gender": "gender",
                    patient_id: "patient", "payment.amount": "pay_now", "payment.mode": "pay_mode", "payment.reference": "reference" },
    rules: (v, add) => {
      if (adding) {
        const r = patientSchema.safeParse({ name: v.name, mobile: v.mobile, age_years: v.age_years, gender: v.gender });
        if (!r.success) for (const i of r.error.issues) add(String(i.path[0]), i.message);
      } else if (!picked) add("patient", "Find the patient, or add them as a new patient.");
      const f = feeProblem(v.fee);
      if (f) add("fee", f);
      const p = payProblem(v.pay_now, v.fee);
      if (p) add("pay_now", p);
    },
    onSubmit: async (v) => {
      const fee = round2(Number(v.fee));
      const paying = fee > 0 && !empty(v.pay_now) ? round2(Number(v.pay_now)) : 0;
      const np = adding ? patientSchema.parse({ name: v.name, mobile: v.mobile, age_years: v.age_years, gender: v.gender }) : null;
      const body = {
        patient_id: adding ? null : picked?.id ?? null,
        patient: np ? { ...np, age_years: Number(np.age_years) } : null,
        doctor_id: v.doctor_id,
        fee: fee.toFixed(2),
        payment: paying > 0 ? { mode: v.pay_mode, amount: paying.toFixed(2), reference: v.pay_mode === "cash" ? "" : v.reference } : null,
      };
      let made: OpdVisit;
      try {
        made = await post<OpdVisit>("/api/opd/visits", body, { "Idempotency-Key": requestKey });
      } catch (e) {
        if (!(e instanceof ApiError && e.transient)) requestKey = newRequestKey();
        throw e;
      }
      requestKey = newRequestKey();
      const due = Number(made.due);
      notify(`Token ${made.token_no} for ${made.doctor.name}.`, {
        kind: "success", title: `${made.patient.name}: visit booked`, duration: 10000,
      });
      if (due > 0) notify(`${rupees(due)} of the fee is still due. Collect it from the bill or Dues.`, { kind: "info" });
      newOpen = false;
      if (!isToday) setQuery({ date: null });
      reload++;
    },
  });

  const chosenDoctor = $derived(doctors.find((d) => d.id === visit.values.doctor_id) ?? null);
  const feeNow = $derived(feeProblem(visit.values.fee) ? 0 : round2(Number(visit.values.fee)));
  const payNowProblem = $derived(payProblem(visit.values.pay_now, visit.values.fee));
  const paidNow = $derived(!payNowProblem && !empty(visit.values.pay_now) ? round2(Number(visit.values.pay_now)) : 0);
  const activeDoctors = $derived(doctors.filter((d) => d.is_active));

  function openNew() {
    picked = null;
    adding = false;
    patientQuery = "";
    family = [];
    requestKey = newRequestKey();
    const preset = activeDoctors.find((d) => d.id === doctorId) ?? (activeDoctors.length === 1 ? activeDoctors[0] : null);
    visit.reset({ ...blank, doctor_id: preset?.id ?? "", fee: preset ? Number(preset.fee) : null });
    newOpen = true;
  }

  // The menu's "New visit" (/opd?new=1) opens the dialog here.
  $effect(() => {
    if (router.query.get("new") !== "1") return;
    setQuery({ new: null });
    if (canManage) openNew();
  });

  function pickDoctor(id: string) {
    visit.values.doctor_id = id;
    const d = doctors.find((x) => x.id === id);
    if (d) visit.values.fee = Number(d.fee);
    visit.touched.doctor_id = true;
    visit.validate();
  }

  const searchPatients = (q: string, page: number, size: number, signal: AbortSignal) =>
    get<Page<Patient>>("/api/patients", { search: q, page, size }, signal);

  function pickPatient(p: Patient) {
    picked = p;
    adding = false;
    visit.validate();
  }

  let familyTimer: ReturnType<typeof setTimeout>;
  function onMobile() {
    visit.field("mobile").oninput();
    clearTimeout(familyTimer);
    const { number } = splitPhone(visit.values.mobile);
    if (number.length < 8) { family = []; return; }
    familyTimer = setTimeout(() => get<Patient[]>("/api/patients/same-mobile", { mobile: visit.values.mobile }).then((r) => (family = r)).catch(() => {}), 250);
  }

  function startNewPatient() {
    adding = true;
    picked = null;
    const q = patientQuery.trim();
    visit.values.name = ""; visit.values.mobile = ""; visit.values.age_years = null; visit.values.gender = "";
    if (/^[+\d\s]{6,}$/.test(q)) visit.values.mobile = q.startsWith("+") ? q.replace(/\s/g, "") : `+91${q.replace(/\D/g, "").slice(-10)}`;
    else if (q) visit.values.name = q;
    onMobile();
    visit.validate();
  }

  // Paid now is checked as it's typed: above the fee shows the error at once.
  function onPay() {
    visit.touched.pay_now = true;
    visit.validate();
  }
  function onFee() {
    visit.touched.fee = true;
    visit.validate();
  }
</script>

{#snippet tokenCell(v: OpdVisit)}<span class="token mono" class:is-off={v.status === "cancelled" || v.status === "done"}>{v.token_no}</span>{/snippet}
{#snippet patientCell(v: OpdVisit)}
  <div class="cell-title">{v.patient.name} <span class="text-xs text-muted mono">{v.patient.patient_no}</span></div>
  <div class="cell-sub">{[ageGender({ age_years: v.patient.age_years, date_of_birth: null, gender: v.patient.gender }), formatPhone(v.patient.mobile)].filter((x) => x && x !== "—").join(" · ")}</div>
{/snippet}
{#snippet statusCell(v: OpdVisit)}
  {@const times = [`Booked ${timeOf(v.created_at)}${v.created_by_name ? ` by ${v.created_by_name}` : ""}`, v.called_at ? `called in ${timeOf(v.called_at)}` : "", v.done_at ? `done ${timeOf(v.done_at)}` : ""].filter(Boolean).join(" · ")}
  <StatusBadge tone={STATUS[v.status].tone} label={STATUS[v.status].label} help={v.status === "cancelled" && v.cancel_reason ? `Cancelled: ${v.cancel_reason}` : times} />
{/snippet}
{#snippet moneyCell(v: OpdVisit)}
  {#if Number(v.fee) > 0}
    <div class="money">{rupees(v.fee)}</div>
    {#if Number(v.due) > 0}<div class="cell-sub"><span class="money money-due">{rupees(v.due)} due</span></div>
    {:else}<div class="cell-sub">Paid</div>{/if}
    {#if v.invoice_id}<div class="cell-sub"><a class="mono" href="/bills/{v.invoice_id}">{v.invoice_no}</a></div>{/if}
  {:else}<span class="text-muted">No fee</span>{/if}
{/snippet}
{#snippet nextCell(v: OpdVisit)}
  {#if canManage && v.status === "waiting"}
    <Button size="sm" variant="primary" icon="arrowRight" loading={busy === v.id} disabled={!!busy} aria-label="Call in {who(v)}"
            tooltip="Send them in to {v.doctor.name}" onclick={() => callIn(v)}>Call in</Button>
  {:else if canManage && v.status === "with_doctor"}
    <Button size="sm" icon="check" loading={busy === v.id} disabled={!!busy} aria-label="Done: {who(v)}"
            tooltip="Seen by the doctor" onclick={() => finish(v)}>Done</Button>
  {/if}
{/snippet}

<PageHeader eyebrow="OPD" title="OPD queue"
            description="Today's visits for each doctor, in token order. Book a visit, call each patient in, and mark them done."
            tip="Tokens start again from 1 for each doctor every day. The queue refreshes by itself every 20 seconds.">
  {#snippet actions()}
    {#if canManage}<Button variant="primary" icon="plus" disabled={!activeDoctors.length}
                           tooltip={activeDoctors.length ? "" : "Add an OPD doctor first"} onclick={openNew}>New visit</Button>{/if}
  {/snippet}
</PageHeader>

<section class="card opd-card" aria-label="OPD queue">
  <div class="tabs" role="tablist" aria-label="Doctor">
    <button class="tab" role="tab" aria-selected={!doctorId} onclick={() => setQuery({ doctor: null })}>
      All doctors{#if allWaiting}<span class="badge badge-info badge-plain tab-count" use:tooltip={"Waiting"}>{allWaiting}</span>{/if}</button>
    {#each tabs as t (t.id)}
      <button class="tab" role="tab" aria-selected={doctorId === t.id} onclick={() => setQuery({ doctor: t.id })}>
        {t.name}{#if t.waiting}<span class="badge badge-info badge-plain tab-count" use:tooltip={"Waiting"}>{t.waiting}</span>{/if}</button>
    {/each}
  </div>

  <div class="toolbar">
    <label class="sr-only" for="opd-date">Day</label>
    <input id="opd-date" class="input opd-date" type="date" max={today} value={day}
           onchange={(e) => setQuery({ date: e.currentTarget.value && e.currentTarget.value !== today ? e.currentTarget.value : null })} />
    {#if !isToday}<Button size="sm" variant="ghost" onclick={() => setQuery({ date: null })}>Today</Button>{/if}
    <label class="sr-only" for="opd-status">Show</label>
    <select id="opd-status" class="select opd-status" value={statusFilter} onchange={(e) => setQuery({ status: e.currentTarget.value || null })}>
      <option value="">Every visit</option>
      {#each Object.entries(STATUS) as [k, s] (k)}<option value={k}>{s.label} ({counts[k as VisitStatus] ?? 0})</option>{/each}
    </select>
    <div class="grow opd-summary text-sm text-muted" aria-live="polite">
      {#if visits}
        {ofDoctor.length} {ofDoctor.length === 1 ? "visit" : "visits"}{isToday ? " today" : ` on ${fmtDate(day)}`} · {counts.waiting} waiting · {counts.done} done
        {#if nowWith} · <span class="font-semibold">with the doctor now: token {nowWith.token_no}</span>{/if}
      {/if}
    </div>
  </div>

  <DataTable label="OPD visits" {rows} loading={loading && !visits} error={loadError} onretry={() => reload++}
             rowClass={(v) => (v.status === "cancelled" ? "is-muted" : v.status === "with_doctor" ? "is-highlight" : "")}
             actions={actionsFor} actionsLabel={(v) => `More for ${who(v)}`}
             empty={{ icon: "list", title: statusFilter ? "No visits with this status." : isToday ? "No visits yet today." : "No visits on this day.",
                      text: canManage && isToday && !statusFilter ? "Book one with New visit." : "" }}
             columns={[
               { key: "token", label: "Token", cell: tokenCell, width: "72px", tip: "The patient's number in this doctor's queue today." },
               { key: "patient", label: "Patient", cell: patientCell, mobile: "title" },
               ...(doctorId ? [] : [{ key: "doctor", label: "Doctor", value: (v: OpdVisit) => v.doctor.name, mobile: "sub" as const }]),
               { key: "status", label: "Status", cell: statusCell, mobile: "end" },
               { key: "fee", label: "Fee", cell: moneyCell, align: "right", nowrap: true, tip: "The consultation fee, what's still due on it, and its bill." },
               { key: "next", label: "Next step", cell: nextCell, align: "right", nowrap: true },
             ]} />
</section>

<!-- New visit -->
<FormDialog bind:open={newOpen} title="New visit" icon="stethoscope" tone="info" wide
            description="Find the patient or add them, choose the doctor and take the fee. They get the doctor's next token."
            submitLabel="Book visit" submitIcon="check" busy={visit.submitting} onsubmit={submitting(visit, "Couldn't book the visit")}>
  <FormErrors form={visit} {labels} idPrefix="nv_" />

  <fieldset class="nv-section">
    <legend class="label">Patient<span class="req" aria-hidden="true">*</span></legend>
    {#if picked}
      <div class="picked">
        <span class="avatar" aria-hidden="true">{picked.name.charAt(0)}</span>
        <div class="grow">
          <div class="font-semibold">{picked.name} <span class="badge badge-navy badge-plain mono">{picked.patient_no}</span></div>
          <div class="text-sm text-muted">{[ageGender(picked), formatPhone(picked.mobile)].filter((x) => x && x !== "—").join(" · ")}</div>
        </div>
        <Button variant="ghost" size="sm" onclick={() => { picked = null; visit.validate(); }}>Change</Button>
      </div>
    {:else if !adding}
      <Combobox id="nv_patient" label="Find a patient" placeholder="Name, mobile or patient number…" searchPage={searchPatients} bind:value={patientQuery}
                onpick={pickPatient} autofocus emptyText="No patient found. Add them as a new patient.">
        {#snippet option(p)}
          <div class="row-between"><span><span class="font-semibold">{p.name}</span> <span class="text-xs text-muted mono">{p.patient_no}</span></span>
            <span class="text-sm text-muted tabular">{formatPhone(p.mobile) || "—"}</span></div>
          <div class="text-xs text-muted">{[p.age_years !== null ? `${p.age_years} Y` : "", GENDER_LABELS[p.gender] ?? p.gender, p.address].filter(Boolean).join(" · ")}</div>
        {/snippet}
      </Combobox>
      <div><Button size="sm" icon="plus" onclick={startNewPatient}>New patient</Button></div>
      {#if visit.error("patient")}<p class="field-error"><Icon name="alert" size="sm" />{visit.error("patient")}</p>{/if}
    {:else}
      <div class="form-grid">
        <Field id="nv_name" label="Full name" required error={visit.error("name")}>
          {#snippet children({ invalid, describedby })}<input id="nv_name" class="input" autocomplete="off" bind:value={visit.values.name} {...visit.field("name")} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
        </Field>
        <Field id="nv_mobile" label="Mobile" optional error={visit.error("mobile")}
               tip="Others already registered with this number are shown, so a family member isn't added twice.">
          {#snippet children({ invalid, describedby })}
            {@const f = visit.field("mobile")}
            <PhoneInput id="nv_mobile" bind:value={visit.values.mobile} {invalid} {describedby} onblur={f.onblur} oninput={onMobile} />
          {/snippet}
        </Field>
      </div>
      {#if family.length}
        <div class="alert alert-info"><Icon name="info" /><div><div class="alert-title">Already registered with this mobile</div>
          <div class="row-wrap family">
            {#each family as f (f.id)}<Button size="sm" onclick={() => pickPatient(f)}>{f.name} · {f.age_years ?? "?"} Y</Button>{/each}
          </div><div class="text-xs family-note">Pick one if it's the same person, or carry on for a family member.</div></div></div>
      {/if}
      <div class="form-grid">
        <Field id="nv_age_years" label="Age (years)" required error={visit.error("age_years")} tip="In completed years; 0 for a baby under one.">
          {#snippet children({ invalid, describedby })}<input id="nv_age_years" class="input tabular" type="number" min="0" max="130" inputmode="numeric" bind:value={visit.values.age_years} {...visit.field("age_years")} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
        </Field>
        <Field id="nv_gender" label="Gender" required error={visit.error("gender")}>
          {#snippet children({ invalid, describedby })}
            <select id="nv_gender" class="select" bind:value={visit.values.gender} {...visit.field("gender")} aria-invalid={invalid} aria-describedby={describedby}>
              <option value="" disabled>Choose…</option><option value="female">Female</option><option value="male">Male</option><option value="other">Other</option>
            </select>
          {/snippet}
        </Field>
      </div>
      <div><button class="link-button" type="button" onclick={() => { adding = false; visit.validate(); }}>Search existing patients instead</button></div>
    {/if}
  </fieldset>

  <div class="form-grid">
    <Field id="nv_doctor_id" label="Doctor" required error={visit.error("doctor_id")} tip="The doctor they'll see. Their fee is filled in, and the token is the next one in their queue today.">
      {#snippet children({ invalid, describedby })}
        <select id="nv_doctor_id" class="select" value={visit.values.doctor_id} onchange={(e) => pickDoctor(e.currentTarget.value)}
                onblur={visit.field("doctor_id").onblur} aria-invalid={invalid} aria-describedby={describedby}>
          <option value="" disabled>Choose…</option>
          {#each activeDoctors as d (d.id)}<option value={d.id}>{d.name}{d.qualification ? ` (${d.qualification})` : ""} · {Number(d.fee) > 0 ? rupees(d.fee) : "no fee"}</option>{/each}
        </select>
      {/snippet}
    </Field>
    <Field id="nv_fee" label="Fee (₹)" required error={visit.error("fee")}
           hint={chosenDoctor && Number(visit.values.fee) !== Number(chosenDoctor.fee) && !feeProblem(visit.values.fee) ? `${chosenDoctor.name}'s usual fee is ${rupees(chosenDoctor.fee)}.` : "0 for no fee: then no bill is made."}
           tip="The consultation fee for this visit, filled in from the doctor. A fee above 0 makes a bill for the visit.">
      {#snippet children({ invalid, describedby })}
        <input id="nv_fee" class="input money" type="number" min="0" step="0.01" inputmode="decimal" bind:value={visit.values.fee}
               {...visit.field("fee")} oninput={onFee} aria-invalid={invalid} aria-describedby={describedby} />
      {/snippet}
    </Field>
  </div>

  {#if feeNow > 0}
    <div class="field">
      <div class="row-between"><div class="label-row"><label class="label" for="nv_pay_now">Paid now (₹)</label>
        <InfoTip about="Paid now" text="What the patient pays at the desk now. Leave it empty if nothing is paid; the rest stays due on the visit's bill and can be collected later from Dues." /></div>
        <button class="link-button" type="button" onclick={() => { visit.values.pay_now = feeNow; onPay(); }}>Full fee</button></div>
      <div class="row pay-row">
        <input id="nv_pay_now" class="input money" type="number" min="0" step="0.01" max={feeNow} inputmode="decimal" placeholder="0"
               bind:value={visit.values.pay_now} name="pay_now" oninput={onPay} onblur={onPay}
               aria-invalid={!!payNowProblem} aria-describedby={payNowProblem ? "nv_pay_now-error" : undefined} />
        <label class="sr-only" for="nv_pay_mode">Paid by</label>
        <select id="nv_pay_mode" class="select pay-mode" bind:value={visit.values.pay_mode}>{#each PAYMENT_MODES as [v, l] (v)}<option value={v}>{l}</option>{/each}</select>
        <InfoTip about="Paid by" text="How the money was taken. The day's collection is split by this (cash in the drawer, UPI, card…)." />
      </div>
      {#if payNowProblem}<p class="field-error" id="nv_pay_now-error" role="alert"><Icon name="alert" size="sm" />{payNowProblem}</p>{/if}
      {#if visit.values.pay_mode !== "cash" && paidNow > 0}
        <input id="nv_reference" class="input mono" placeholder="UPI / card reference" aria-label="Payment reference" bind:value={visit.values.reference} {...visit.field("reference")} />
        {#if visit.error("reference")}<p class="field-error"><Icon name="alert" size="sm" />{visit.error("reference")}</p>{/if}
      {/if}
    </div>
    <div class="nv-due" class:is-due={feeNow - paidNow > 0}>
      <span>{feeNow - paidNow > 0 ? "Due after this" : "Nothing due"}</span><span class="money">{rupees(round2(feeNow - paidNow))}</span>
    </div>
  {:else if !feeProblem(visit.values.fee)}
    <p class="text-sm text-muted">No fee for this visit, so no bill is made.</p>
  {/if}
</FormDialog>

<!-- Cancel a visit -->
<FormDialog bind:open={cancelOpen} title={cancelling ? `Cancel token ${cancelling.token_no}?` : "Cancel visit"} icon="x" tone="destructive"
            description={cancelling ? `${cancelling.patient.name}, waiting for ${cancelling.doctor.name}.` : ""}
            submitLabel="Cancel visit" submitVariant="destructive" cancelLabel="Keep it" busy={cancelForm.submitting} busyLabel="Cancelling…"
            onsubmit={submitting(cancelForm, "Couldn't cancel the visit")}>
  <FormErrors form={cancelForm} labels={{ reason: "Reason" }} idPrefix="cv_" />
  <Field id="cv_reason" label="Reason" required error={cancelForm.error("reason")} hint="For example: patient left, doctor not available."
         tip="Kept with the visit and in the activity log.">
    {#snippet children({ invalid, describedby })}
      <input id="cv_reason" class="input" autocomplete="off" bind:value={cancelForm.values.reason} {...cancelForm.field("reason")} aria-invalid={invalid} aria-describedby={describedby} />
    {/snippet}
  </Field>
  {#if cancelling && Number(cancelling.paid) > 0}
    <div class="alert alert-info"><Icon name="info" /><div>{rupees(cancelling.paid)} was paid for this visit. The bill is left as it is:
      {#if cancelling.invoice_id}<a href="/bills/{cancelling.invoice_id}">refund it from bill {cancelling.invoice_no}</a>{:else}refund it from the bill{/if} if needed.</div></div>
  {/if}
</FormDialog>

<style>
  .token {
    display: inline-grid; place-items: center; min-width: 38px; height: 32px; padding: 0 8px; border-radius: var(--radius-sm);
    background: var(--info-soft); color: var(--primary-text); font-weight: 700; font-size: 15px;
  }
  .token.is-off { background: var(--muted); color: var(--muted-foreground); }
  .opd-date { width: auto; flex: none; }
  .opd-status { width: auto; flex: none; }
  .opd-summary { min-width: 200px; }
  .nv-section { border: 0; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 12px; }
  .nv-section legend { margin-bottom: 6px; padding: 0; }
  .picked { display: flex; align-items: center; gap: 12px; padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--radius); }
  .family { gap: 6px; margin-top: 6px; }
  .family-note { margin-top: 6px; }
  .pay-row { gap: 8px; align-items: center; }
  .pay-mode { flex: none; width: 140px; }
  .nv-due { display: flex; justify-content: space-between; font-weight: 600; }
  .nv-due.is-due { color: var(--destructive); }
  .opd-card :global(tr.is-muted) { opacity: .65; }
  .opd-card :global(tr.is-highlight) { background: var(--warning-soft); }
  @media (max-width: 640px) {
    .opd-date, .opd-status { flex: 1 1 140px; }
    .opd-summary { flex-basis: 100%; }
    .pay-mode { width: 120px; }
  }
</style>
