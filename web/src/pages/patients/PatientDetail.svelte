<script lang="ts">
  import { z } from "zod";
  import Button from "../../components/Button.svelte";
  import Card from "../../components/Card.svelte";
  import DataTable from "../../components/DataTable.svelte";
  import Dialog from "../../components/Dialog.svelte";
  import Field from "../../components/Field.svelte";
  import FormErrors from "../../components/FormErrors.svelte";
  import Icon from "../../components/Icon.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import PhoneInput from "../../components/PhoneInput.svelte";
  import StatusBadge from "../../components/StatusBadge.svelte";
  import type { RowAction } from "../../components/RowMenu.svelte";
  import { get, put } from "../../lib/api";
  import { todayISO } from "../../lib/dates";
  import { Form } from "../../lib/form.svelte";
  import { date, dateTime, rupees } from "../../lib/format";
  import { formatPhone } from "../../lib/phone";
  import { router } from "../../lib/router.svelte";
  import { optionalEmail, optionalText, phone, submitting, text, wholeNumber } from "../../lib/schemas";
  import { session } from "../../lib/session.svelte";
  import { notify } from "../../lib/toast.svelte";
  import { tooltip } from "../../lib/tooltip";
  import { ageGender, GENDER_LABELS, type BillSummary, type Page, type Patient } from "../../lib/types";

  let { params }: { params: Record<string, string> } = $props();
  const id = $derived(params.id);

  const SIZE = 10;
  const billPage = $derived(Number(router.query.get("page") ?? 1) || 1);

  let patient = $state<Patient | null>(null);
  let loadError = $state("");
  let reload = $state(0);
  let others = $state<Patient[]>([]);
  let bills = $state<Page<BillSummary> | null>(null);
  let billsError = $state("");
  let billsLoading = $state(false);
  let billsReload = $state(0);

  $effect(() => {
    const ctrl = new AbortController();
    const pid = id;
    reload;
    get<Patient>(`/api/patients/${pid}`, undefined, ctrl.signal)
      .then((p) => {
        patient = p;
        loadError = "";
        others = [];
        if (p.mobile) {
          get<Patient[]>("/api/patients/same-mobile", { mobile: p.mobile, exclude: p.id }, ctrl.signal)
            .then((list) => (others = list))
            .catch(() => { /* a nice-to-have: say nothing if it fails */ });
        }
      })
      .catch((e) => { if (e.name !== "AbortError") loadError = e.message; });
    return () => ctrl.abort();
  });

  $effect(() => {
    const ctrl = new AbortController();
    const query = { patient_id: id, page: billPage, size: SIZE };
    billsReload;
    billsLoading = true;
    get<Page<BillSummary>>("/api/bills", query, ctrl.signal)
      .then((d) => { bills = d; billsError = ""; })
      .catch((e) => { if (e.name !== "AbortError") billsError = e.message; })
      .finally(() => { billsLoading = false; });
    return () => ctrl.abort();
  });

  function billActions(b: BillSummary): RowAction[] {
    return [
      { label: "View bill", icon: "eye", href: `/bills/${b.id}` },
      { label: "Print", icon: "printer", href: `/bills/${b.id}/print`, newTab: true },
      ...(b.status !== "cancelled" && Number(b.due) > 0 && session.can("payments.collect") ? [{ label: "Collect due", icon: "wallet", href: `/bills/${b.id}?collect=1` }] : []),
    ];
  }

  // ---------- edit ----------
  const today = todayISO();
  const schema = z.object({
    name: text("Enter the patient's name.", 200, 2),
    guardian_name: optionalText(200),
    age_years: wholeNumber({ min: 0, max: 130, label: "the age in years" }),
    date_of_birth: z.string().refine((v) => !v || v <= today, "The date of birth can't be in the future."),
    gender: z.string().refine((v) => v in GENDER_LABELS, "Choose the gender."),
    mobile: phone(false),
    email: optionalEmail,
    address: optionalText(500),
  });
  const blank = { name: "", guardian_name: "", age_years: null as number | null, date_of_birth: "", gender: "", mobile: "", email: "", address: "" };
  const labels: Record<string, string> = { name: "Name", guardian_name: "Guardian", age_years: "Age", date_of_birth: "Date of birth", gender: "Gender",
                                           mobile: "Mobile", email: "Email", address: "Address", __all__: "Age or date of birth" };

  let dialogOpen = $state(false);
  const form = new Form({
    schema, initial: blank,
    rules: (v, add) => { if ((v.age_years === null || v.age_years === "" || v.age_years === undefined) && !v.date_of_birth) add("age_years", "Give the age in years, or the date of birth."); },
    onSubmit: async (v) => {
      if (!patient) return;
      patient = await put<Patient>(`/api/patients/${patient.id}`, {
        name: v.name, guardian_name: v.guardian_name, gender: v.gender || null,
        age_years: v.age_years === null || v.age_years === "" ? null : Number(v.age_years),
        date_of_birth: v.date_of_birth || null, mobile: v.mobile, email: v.email, address: v.address,
      });
      notify(`${patient.name}'s details saved.`);
      dialogOpen = false;
      reload++;
      billsReload++;
    },
    serverFields: { __all__: "age_years" },
  });

  function openEdit() {
    if (!patient) return;
    const p = patient;
    form.reset({ name: p.name, guardian_name: p.guardian_name, age_years: p.age_years, date_of_birth: p.date_of_birth ?? "",
                 gender: p.gender || "", mobile: p.mobile, email: p.email, address: p.address });
    dialogOpen = true;
  }
</script>

{#snippet billCell(b: BillSummary)}
  <div class="cell-title mono"><a href="/bills/{b.id}">{b.invoice_no}</a></div>
  {#if b.referring_doctor_name}<div class="cell-sub">Ref. {b.referring_doctor_name}</div>{/if}
{/snippet}
{#snippet dateCell(b: BillSummary)}<span class="text-sm nowrap" use:tooltip={`Made ${dateTime(b.created_at)}`}>{date(b.bill_date)}</span>{/snippet}
{#snippet dueCell(b: BillSummary)}<span class="money" class:money-due={Number(b.due) > 0}>{rupees(b.due)}</span>{/snippet}
{#snippet statusCell(b: BillSummary)}<StatusBadge bill={b} />{/snippet}
{#snippet otherCell(o: Patient)}<div class="cell-title"><a href="/patients/{o.id}">{o.name}</a></div><div class="cell-sub mono">{o.patient_no}</div>{/snippet}

{#if loadError}
  <PageHeader eyebrow="Patients" title="Patient" />
  <div class="alert alert-destructive" role="alert"><Icon name="alert" /><div>{loadError} <button class="link-button" onclick={() => reload++}>Try again</button></div></div>
  <p class="mt-3"><a href="/patients">Back to patients</a></p>
{:else if !patient}
  <div class="empty" aria-busy="true">Loading…</div>
{:else}
  <PageHeader eyebrow="Patients" title={patient.name} description="Patient {patient.patient_no} · registered {date(patient.created_at)}">
    {#snippet actions()}
      {#if session.can("patients.manage")}<Button icon="edit" onclick={openEdit} tooltip="Change the name, age, mobile or address">Edit</Button>{/if}
      {#if session.can("billing.create")}<Button variant="primary" icon="plus" href="/bills/new?patient={patient?.id}">New bill for this patient</Button>{/if}
    {/snippet}
  </PageHeader>

  <div class="stack">
    <Card title="Details">
      <dl class="dl">
        <div><dt>Patient number</dt><dd class="mono">{patient.patient_no}</dd></div>
        <div><dt>Age / gender</dt><dd>{ageGender(patient)}</dd></div>
        <div><dt>Date of birth</dt><dd>{date(patient.date_of_birth)}</dd></div>
        <div><dt>Guardian (C/O)</dt><dd>{patient.guardian_name || "—"}</dd></div>
        <div><dt>Mobile</dt><dd class="tabular">{#if patient.mobile}<a href="tel:{patient.mobile}">{formatPhone(patient.mobile)}</a>{:else}—{/if}</dd></div>
        <div><dt>Email</dt><dd class="break">{patient.email || "—"}</dd></div>
        <div class="full"><dt>Address</dt><dd>{patient.address || "—"}</dd></div>
      </dl>
    </Card>

    {#if others.length}
      <Card title="Others with this mobile" flush
            description="Family members often share a number. Check you have the right person before billing.">
        <DataTable label="Others with this mobile" rows={others} rowHref={(o) => `/patients/${o.id}`}
                   actions={(o) => [{ label: "Open patient", icon: "eye", href: `/patients/${o.id}` },
                                    ...(session.can("billing.create") ? [{ label: "New bill", icon: "plus", href: `/bills/new?patient=${o.id}` }] : [])]}
                   columns={[
                     { key: "name", label: "Patient", cell: otherCell, mobile: "title" },
                     { key: "age", label: "Age / gender", value: (o) => ageGender(o), mobile: "end" },
                     { key: "guardian", label: "Guardian (C/O)", value: (o) => o.guardian_name || "—" },
                   ]} />
      </Card>
    {/if}

    <Card title="Bills" flush id="bills">
      <DataTable label="Bills of {patient.name}" rows={bills?.items ?? []} loading={billsLoading} error={billsError} onretry={() => billsReload++}
                 page={bills && bills.total > bills.size ? bills : null} rowHref={(b) => `/bills/${b.id}`} actions={billActions}
                 actionsLabel={(b) => `Actions for ${b.invoice_no}`}
                 empty={{ icon: "receipt", title: "No bills for this patient yet." }}
                 columns={[
                   { key: "bill", label: "Bill", cell: billCell, mobile: "title" },
                   { key: "date", label: "Date", cell: dateCell, mobile: "sub" },
                   { key: "total", label: "Total", value: (b) => rupees(b.total), align: "right", class: "money" },
                   { key: "paid", label: "Paid", value: (b) => rupees(b.paid), align: "right", class: "money", mobile: "hide", tip: "Payments taken, less any refunds." },
                   { key: "due", label: "Due", cell: dueCell, align: "right" },
                   { key: "status", label: "Status", cell: statusCell, mobile: "end" },
                 ]} />
    </Card>
  </div>
{/if}

<Dialog bind:open={dialogOpen} title="Edit patient details" icon="user" tone="info" wide
        description="Changes show on new bills. Bills already made keep the details they were printed with.">
  <form id="patient-form" class="stack" onsubmit={submitting(form, "Couldn't save")} novalidate>
    <FormErrors {form} {labels} idPrefix="p_" />
    <div class="form-grid">
      <Field id="p_name" label="Name" required error={form.error("name")}>
        {#snippet children({ invalid, describedby })}
          <input id="p_name" class="input" autocomplete="off" bind:value={form.values.name} {...form.field("name")} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
      <Field id="p_guardian_name" label="Guardian (C/O)" optional error={form.error("guardian_name")}
             tip="Father, husband or whoever the patient comes with. Printed on the bill as C/O.">
        {#snippet children({ invalid, describedby })}
          <input id="p_guardian_name" class="input" bind:value={form.values.guardian_name} {...form.field("guardian_name")} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
      <Field id="p_age_years" label="Age in years" error={form.error("age_years")}
             tip="Give the age, or the date of birth (the age is then worked out from it). One of the two is needed.">
        {#snippet children({ invalid, describedby })}
          <input id="p_age_years" class="input tabular" type="number" min="0" max="130" step="1" inputmode="numeric" bind:value={form.values.age_years}
                 {...form.field("age_years")} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
      <Field id="p_date_of_birth" label="Date of birth" optional error={form.error("date_of_birth")}>
        {#snippet children({ invalid, describedby })}
          <input id="p_date_of_birth" class="input" type="date" max={today} bind:value={form.values.date_of_birth} {...form.field("date_of_birth")}
                 aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
      <Field id="p_gender" label="Gender" required error={form.error("gender")}>
        {#snippet children({ invalid, describedby })}
          <select id="p_gender" class="select" bind:value={form.values.gender} {...form.field("gender")} aria-invalid={invalid} aria-describedby={describedby}>
            <option value="" disabled>Choose…</option>
            {#each Object.entries(GENDER_LABELS) as [value, label] (value)}<option {value}>{label}</option>{/each}
          </select>
        {/snippet}
      </Field>
      <Field id="p_mobile" label="Mobile" optional error={form.error("mobile")}
             tip="Choose the country code, then type the number. Bills and reports are sent to this number.">
        {#snippet children({ invalid, describedby })}
          {@const f = form.field("mobile")}
          <PhoneInput id="p_mobile" bind:value={form.values.mobile} {invalid} {describedby} onblur={f.onblur} oninput={f.oninput} />
        {/snippet}
      </Field>
      <div class="full">
        <Field id="p_email" label="Email" optional error={form.error("email")} tip="Used to email reports, if the patient wants them.">
          {#snippet children({ invalid, describedby })}
            <input id="p_email" class="input" type="email" autocomplete="off" bind:value={form.values.email} {...form.field("email")} aria-invalid={invalid} aria-describedby={describedby} />
          {/snippet}
        </Field>
      </div>
      <div class="full">
        <Field id="p_address" label="Address" optional error={form.error("address")}>
          {#snippet children({ invalid, describedby })}
            <textarea id="p_address" class="textarea" rows="3" bind:value={form.values.address} {...form.field("address")} aria-invalid={invalid} aria-describedby={describedby}></textarea>
          {/snippet}
        </Field>
      </div>
    </div>
  </form>
  {#snippet footer()}
    <Button onclick={() => (dialogOpen = false)}>Cancel</Button>
    <Button variant="primary" type="submit" form="patient-form" loading={form.submitting} loadingText="Saving…">Save changes</Button>
  {/snippet}
</Dialog>

<style>
  .break { overflow-wrap: anywhere; }
</style>
