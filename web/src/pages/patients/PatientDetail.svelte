<script lang="ts">
  import Dialog from "../../components/Dialog.svelte";
  import Field from "../../components/Field.svelte";
  import Icon from "../../components/Icon.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import Pagination from "../../components/Pagination.svelte";
  import { ApiError, get, put } from "../../lib/api";
  import { date, dateTime, rupees } from "../../lib/format";
  import { router, setQuery } from "../../lib/router.svelte";
  import { session } from "../../lib/session.svelte";
  import { notify, notifyError } from "../../lib/toast.svelte";
  import { ageGender, GENDER_LABELS, type BillSummary, type Gender, type Page, type Patient } from "../../lib/types";

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
    billsLoading = true;
    get<Page<BillSummary>>("/api/bills", query, ctrl.signal)
      .then((d) => { bills = d; billsError = ""; })
      .catch((e) => { if (e.name !== "AbortError") billsError = e.message; })
      .finally(() => { billsLoading = false; });
    return () => ctrl.abort();
  });

  const BILL_STATUS: Record<string, [string, string]> = {
    confirmed: ["badge-success", "Confirmed"], on_hold: ["badge-warning", "On hold"], cancelled: ["badge-destructive", "Cancelled"],
  };

  // ---------- edit ----------
  type Form = { name: string; guardian_name: string; age_years: number | null; date_of_birth: string; gender: Gender | "";
                mobile: string; email: string; address: string };

  let dialogOpen = $state(false);
  let form = $state<Form>({ name: "", guardian_name: "", age_years: null, date_of_birth: "", gender: "", mobile: "", email: "", address: "" });
  let errors = $state<Record<string, string>>({});
  let saving = $state(false);
  const today = new Date().toISOString().slice(0, 10);

  function openEdit() {
    if (!patient) return;
    const p = patient;
    form = { name: p.name, guardian_name: p.guardian_name, age_years: p.age_years,
             date_of_birth: p.date_of_birth ?? "", gender: (p.gender as Gender) || "", mobile: p.mobile, email: p.email, address: p.address };
    errors = {};
    dialogOpen = true;
  }

  async function save() {
    if (!patient) return;
    saving = true;
    errors = {};
    try {
      patient = await put<Patient>(`/api/patients/${patient.id}`, {
        name: form.name, guardian_name: form.guardian_name, gender: form.gender || null,
        age_years: typeof form.age_years === "number" ? form.age_years : null,
        date_of_birth: form.date_of_birth || null,
        mobile: form.mobile, email: form.email.trim(), address: form.address,
      });
      notify(`${patient.name}'s details saved.`);
      dialogOpen = false;
      reload++;
    } catch (e) {
      if (e instanceof ApiError && Object.keys(e.fieldErrors).length) errors = e.fieldErrors;
      else notifyError(e, { title: "Couldn't save" });
    } finally {
      saving = false;
    }
  }

  // A rule across fields (age or date of birth) comes back without a field; show it at the top of the form.
  const formError = $derived(errors.__all__ ?? "");
</script>

{#if loadError}
  <PageHeader eyebrow="Patients" title="Patient" />
  <div class="alert alert-destructive" role="alert"><Icon name="alert" /><div>{loadError} <button class="link-button" onclick={() => reload++}>Try again</button></div></div>
  <p class="mt-3"><a href="/patients">Back to patients</a></p>
{:else if !patient}
  <div class="empty" aria-busy="true">Loading…</div>
{:else}
  <PageHeader eyebrow="Patients" title={patient.name} description="Registered {date(patient.created_at)}">
    {#snippet actions()}
      <span class="badge badge-navy badge-plain mono">{patient?.patient_no}</span>
      {#if session.can("patients.manage")}<button class="btn btn-outline" onclick={openEdit}><Icon name="edit" /> Edit</button>{/if}
      {#if session.can("billing.create")}<a class="btn btn-primary" href="/bills/new?patient={patient?.id}"><Icon name="plus" /> New bill for this patient</a>{/if}
    {/snippet}
  </PageHeader>

  <div class="stack">
    <section class="card">
      <div class="card-header"><h2 class="card-title">Details</h2></div>
      <div class="card-content">
        <dl class="dl">
          <div><dt>Patient number</dt><dd class="mono">{patient.patient_no}</dd></div>
          <div><dt>Age / gender</dt><dd>{ageGender(patient)}</dd></div>
          <div><dt>Date of birth</dt><dd>{date(patient.date_of_birth)}</dd></div>
          <div><dt>Guardian (C/O)</dt><dd>{patient.guardian_name || "—"}</dd></div>
          <div><dt>Mobile</dt><dd class="tabular">{patient.mobile || "—"}</dd></div>
          <div><dt>Email</dt><dd>{patient.email || "—"}</dd></div>
          <div class="full"><dt>Address</dt><dd>{patient.address || "—"}</dd></div>
        </dl>
      </div>
    </section>

    {#if others.length}
      <section class="card">
        <div class="card-header">
          <h2 class="card-title">Others with this mobile</h2>
          <p class="card-description">Family members often share a number. Check you have the right person before billing.</p>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Patient</th><th>Age / gender</th><th>Guardian (C/O)</th></tr></thead>
            <tbody>
              {#each others as o (o.id)}
                <tr>
                  <td><div class="cell-title"><a href="/patients/{o.id}">{o.name}</a></div><div class="cell-sub mono">{o.patient_no}</div></td>
                  <td>{ageGender(o)}</td>
                  <td>{o.guardian_name || "—"}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </section>
    {/if}

    <section class="card">
      <div class="card-header"><h2 class="card-title">Bills</h2></div>
      {#if billsError}
        <div class="card-content"><div class="alert alert-destructive" role="alert"><Icon name="alert" /><div>{billsError}</div></div></div>
      {:else if bills}
        <div class="table-wrap" aria-busy={billsLoading}>
          <table class="table">
            <thead><tr><th>Bill</th><th>Date</th><th class="num">Total</th><th class="num">Paid</th><th class="num">Due</th><th>Status</th></tr></thead>
            <tbody>
              {#each bills.items as b (b.id)}
                {@const st = BILL_STATUS[b.status] ?? ["badge-info", b.status]}
                <tr>
                  <td><div class="cell-title mono"><a href="/bills/{b.id}">{b.invoice_no}</a></div>
                    {#if b.referring_doctor_name}<div class="cell-sub">Ref. {b.referring_doctor_name}</div>{/if}</td>
                  <td class="text-sm nowrap" title={dateTime(b.created_at)}>{date(b.bill_date)}</td>
                  <td class="num money">{rupees(b.total)}</td>
                  <td class="num money">{rupees(b.paid)}</td>
                  <td class="num money" class:money-due={Number(b.due) > 0}>{rupees(b.due)}</td>
                  <td><span class="badge {st[0]}">{st[1]}</span></td>
                </tr>
              {:else}
                <tr><td colspan="6"><div class="empty"><Icon name="receipt" />No bills for this patient yet.</div></td></tr>
              {/each}
            </tbody>
          </table>
        </div>
        {#if bills.total > bills.size}<Pagination page={bills.page} size={bills.size} total={bills.total} onchange={(p) => setQuery({ page: p }, { replace: false })} />{/if}
      {:else}
        <div class="empty" aria-busy="true">Loading…</div>
      {/if}
    </section>
  </div>
{/if}

<Dialog bind:open={dialogOpen} title="Edit patient details" icon="user" tone="info" wide
        description="Changes show on new bills. Bills already made keep the details they were printed with.">
  <form id="patient-form" class="stack" onsubmit={(e) => { e.preventDefault(); save(); }} novalidate>
    {#if formError}<div class="alert alert-destructive" role="alert"><Icon name="alert" /><div>{formError}</div></div>{/if}
    <div class="grid-2">
      <Field id="p_name" label="Name" required error={errors.name}>
        {#snippet children({ invalid, describedby })}
          <input id="p_name" class="input" bind:value={form.name} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
      <Field id="p_guardian" label="Guardian (C/O)" error={errors.guardian_name} hint="Father, husband or whoever the patient comes with.">
        {#snippet children({ invalid, describedby })}
          <input id="p_guardian" class="input" bind:value={form.guardian_name} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
    </div>
    <div class="grid-3">
      <Field id="p_age" label="Age in years" error={errors.age_years} hint="Or give the date of birth.">
        {#snippet children({ invalid, describedby })}
          <input id="p_age" class="input" type="number" min="0" max="130" step="1" inputmode="numeric" bind:value={form.age_years}
                 aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
      <Field id="p_dob" label="Date of birth" error={errors.date_of_birth}>
        {#snippet children({ invalid, describedby })}
          <input id="p_dob" class="input" type="date" max={today} bind:value={form.date_of_birth} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
      <Field id="p_gender" label="Gender" required error={errors.gender}>
        {#snippet children({ invalid, describedby })}
          <select id="p_gender" class="select" bind:value={form.gender} aria-invalid={invalid} aria-describedby={describedby}>
            <option value="" disabled>Choose…</option>
            {#each Object.entries(GENDER_LABELS) as [value, label] (value)}<option {value}>{label}</option>{/each}
          </select>
        {/snippet}
      </Field>
    </div>
    <div class="grid-2">
      <Field id="p_mobile" label="Mobile" error={errors.mobile}>
        {#snippet children({ invalid, describedby })}
          <input id="p_mobile" class="input" type="tel" inputmode="tel" bind:value={form.mobile} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
      <Field id="p_email" label="Email" error={errors.email}>
        {#snippet children({ invalid, describedby })}
          <input id="p_email" class="input" type="email" bind:value={form.email} aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
    </div>
    <Field id="p_address" label="Address" error={errors.address}>
      {#snippet children({ invalid, describedby })}
        <textarea id="p_address" class="textarea" rows="3" bind:value={form.address} aria-invalid={invalid} aria-describedby={describedby}></textarea>
      {/snippet}
    </Field>
  </form>
  {#snippet footer()}
    <button class="btn btn-outline" type="button" onclick={() => (dialogOpen = false)}>Cancel</button>
    <button class="btn btn-primary" type="submit" form="patient-form" disabled={saving}>{saving ? "Saving…" : "Save changes"}</button>
  {/snippet}
</Dialog>
