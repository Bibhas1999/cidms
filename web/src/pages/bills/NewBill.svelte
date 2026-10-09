<script lang="ts">
  import Combobox from "../../components/Combobox.svelte";
  import Field from "../../components/Field.svelte";
  import Icon from "../../components/Icon.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import TestSelect from "../../components/TestSelect.svelte";
  import { ApiError, get, newRequestKey, post } from "../../lib/api";
  import { PAYMENT_MODES, type Bill, type Doctor, type LabTest, type Patient, type PaymentMode } from "../../lib/bill-types";
  import { rupees } from "../../lib/format";
  import { navigate, router, setBeforeLeave } from "../../lib/router.svelte";
  import { notify, notifyError } from "../../lib/toast.svelte";
  import type { Page } from "../../lib/types";

  // One screen for the front desk: find or add the patient, the referring doctor, the tests, the discount
  // and what's paid now. Prices come from the catalogue; the server works out every total again.

  // ---------- patient ----------
  let patient = $state<Patient | null>(null);
  let addingPatient = $state(false);
  let patientQuery = $state("");
  let np = $state({ name: "", guardian_name: "", age_years: "", gender: "", mobile: "", address: "" });
  let family = $state<Patient[]>([]);

  const preset = router.query.get("patient");
  $effect(() => {
    if (preset) get<Patient>(`/api/patients/${preset}`).then((p) => (patient = p)).catch(() => {});
  });

  const searchPatients = (q: string, signal: AbortSignal) => get<Page<Patient>>("/api/patients", { search: q, size: 8 }, signal).then((r) => r.items);

  let familyTimer: ReturnType<typeof setTimeout>;
  function onMobile() {
    clearTimeout(familyTimer);
    const digits = np.mobile.replace(/\D/g, "");
    if (digits.length < 10) { family = []; return; }
    familyTimer = setTimeout(() => get<Patient[]>("/api/patients/same-mobile", { mobile: np.mobile }).then((r) => (family = r)).catch(() => {}), 250);
  }

  function startNewPatient() {
    addingPatient = true;
    patient = null;
    const q = patientQuery.trim();
    if (/^[+\d\s]{6,}$/.test(q)) np.mobile = q; else if (q) np.name = q;
    onMobile();
  }

  // ---------- doctor ----------
  let doctorText = $state("");
  let doctor = $state<Doctor | null>(null);
  const searchDoctors = (q: string, signal: AbortSignal) => get<Page<Doctor>>("/api/doctors", { search: q, active: true, size: 8 }, signal).then((r) => r.items);

  // ---------- tests ----------
  interface Line { test: LabTest; quantity: number }
  let lines = $state<Line[]>([]);
  const onBill = $derived(new Set(lines.map((l) => l.test.id)));

  // As on the old Supreme Invoice page: select the test (or tick several), see the rate, press Add.
  let picked = $state<LabTest[]>([]);
  const pickedPrice = $derived(picked.reduce((sum, t) => sum + Number(t.price), 0));

  function addPicked() {
    if (!picked.length) { errors = { ...errors, lines: "Select a test first." }; return; }
    for (const t of picked) {
      const line = lines.find((l) => l.test.id === t.id);
      if (line) line.quantity += 1;
      else lines.push({ test: t, quantity: 1 });
    }
    picked = [];
    errors = { ...errors, lines: "" };
  }

  // ---------- money ----------
  let discountType = $state<"none" | "percent" | "amount">("none");
  let discountValue = $state("");
  let payNow = $state("");
  let payMode = $state<PaymentMode>("cash");
  let payRef = $state("");
  let notes = $state("");
  let hold = $state(false);

  const round2 = (n: number) => Math.round(n * 100) / 100;
  const subtotal = $derived(round2(lines.reduce((s, l) => s + Number(l.test.price) * l.quantity, 0)));
  const discount = $derived(
    discountType === "percent" ? round2((subtotal * Math.min(100, Number(discountValue) || 0)) / 100)
      : discountType === "amount" ? Math.min(subtotal, round2(Number(discountValue) || 0)) : 0,
  );
  const total = $derived(round2(subtotal - discount));
  const paying = $derived(Math.min(total, round2(Number(payNow) || 0)));
  const dueAfter = $derived(round2(total - paying));

  // ---------- save ----------
  let errors = $state<Record<string, string>>({});
  let saving = $state(false);
  let requestKey = newRequestKey();
  const dirty = $derived(!!(patient || addingPatient || lines.length));

  $effect(() => {
    setBeforeLeave(dirty && !saving ? () => confirm("This bill isn't saved. Leave without saving?") : null);
    return () => setBeforeLeave(null);
  });

  async function save(print: boolean) {
    errors = {};
    if (!patient && !addingPatient) { errors = { patient: "Choose a patient or add a new one." }; return; }
    if (!lines.length) { errors = { lines: "Add at least one test." }; return; }
    saving = true;
    const body = {
      patient_id: patient?.id ?? null,
      patient: addingPatient ? { ...np, age_years: np.age_years === "" ? null : Number(np.age_years), gender: np.gender || "other" } : null,
      referring_doctor_id: doctor && doctor.name === doctorText ? doctor.id : null,
      referring_doctor_name: doctor && doctor.name === doctorText ? "" : doctorText,
      lines: lines.map((l) => ({ test_id: l.test.id, quantity: l.quantity })),
      discount_type: discountType, discount_value: discountType === "none" ? "0" : String(Number(discountValue) || 0),
      payments: paying > 0 ? [{ mode: payMode, amount: paying.toFixed(2), reference: payRef }] : [],
      notes, hold,
    };
    try {
      const bill = await post<Bill>("/api/bills", body, { "Idempotency-Key": requestKey });
      setBeforeLeave(null);
      notify(`${bill.invoice_no} for ${bill.patient_name}: ${rupees(bill.total)}${Number(bill.due) > 0 ? `, ${rupees(bill.due)} due` : ", fully paid"}.`, { title: "Bill saved" });
      if (print) window.open(`/bills/${bill.id}/print`, "_blank", "noopener");
      navigate(`/bills/${bill.id}`, { replace: true });
    } catch (e) {
      requestKey = newRequestKey();
      if (e instanceof ApiError && Object.keys(e.fieldErrors).length) {
        errors = Object.fromEntries(Object.entries(e.fieldErrors).map(([k, v]) => [k.replace(/^patient\./, "np_"), v]));
        notifyError(e, { title: "Check the bill" });
      } else notifyError(e, { title: "Couldn't save the bill" });
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

<PageHeader eyebrow="Front desk" title="New bill" description="Find the patient, add the tests, take the payment. Prices come from your catalogue.">
  {#snippet actions()}<span class="text-sm text-muted hide-sm"><span class="kbd">Ctrl</span> + <span class="kbd">Enter</span> saves · <span class="kbd">Ctrl</span> + <span class="kbd">P</span> saves and prints</span>{/snippet}
</PageHeader>

<div class="grid-3 items-start">
  <div class="span-2 stack">
    <section class="card" aria-labelledby="p-title">
      <div class="card-header"><div><h2 class="card-title" id="p-title"><span class="step">1</span> Patient</h2>
        <p class="card-description">Search by name, mobile or patient number, or add someone new.</p></div></div>
      <div class="card-content stack">
        {#if patient}
          <div class="picked">
            <span class="avatar" aria-hidden="true">{patient.name.charAt(0)}</span>
            <div class="grow">
              <div class="font-semibold">{patient.name} <span class="badge badge-navy badge-plain mono">{patient.patient_no}</span></div>
              <div class="text-sm text-muted">{[patient.age_years !== null ? `${patient.age_years} Y` : "", patient.gender, patient.mobile, patient.guardian_name ? `C/O ${patient.guardian_name}` : ""].filter(Boolean).join(" · ")}</div>
            </div>
            <button class="btn btn-ghost btn-sm" onclick={() => (patient = null)}>Change</button>
          </div>
        {:else if !addingPatient}
          <Combobox id="patient-search" label="Find a patient" placeholder="Name, mobile or patient number…" search={searchPatients} bind:value={patientQuery}
                    onpick={(p) => (patient = p)} autofocus emptyText="No patient found. Add them as a new patient.">
            {#snippet option(p)}
              <div class="row-between"><span><span class="font-semibold">{p.name}</span> <span class="text-xs text-muted mono">{p.patient_no}</span></span>
                <span class="text-sm text-muted tabular">{p.mobile || "—"}</span></div>
              <div class="text-xs text-muted">{[p.age_years !== null ? `${p.age_years} Y` : "", p.gender, p.guardian_name ? `C/O ${p.guardian_name}` : "", p.address].filter(Boolean).join(" · ")}</div>
            {/snippet}
          </Combobox>
          <div><button class="btn btn-outline btn-sm" onclick={startNewPatient}><Icon name="plus" size="sm" /> New patient</button></div>
          {#if errors.patient}<p class="field-error"><Icon name="alert" size="sm" />{errors.patient}</p>{/if}
        {:else}
          <div class="grid-2">
            <Field id="np-name" label="Full name" required error={errors.np_name}>
              {#snippet children({ invalid, describedby })}<input id="np-name" class="input" bind:value={np.name} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
            </Field>
            <Field id="np-mobile" label="Mobile" error={errors.np_mobile}>
              {#snippet children({ invalid, describedby })}<input id="np-mobile" class="input tabular" type="tel" bind:value={np.mobile} oninput={onMobile} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
            </Field>
          </div>
          {#if family.length}
            <div class="alert alert-info"><Icon name="info" /><div><div class="alert-title">Already registered with this mobile</div>
              <div class="row-wrap" style="margin-top: 6px">
                {#each family as f (f.id)}<button class="btn btn-outline btn-sm" type="button" onclick={() => { patient = f; addingPatient = false; }}>{f.name} · {f.age_years ?? "?"} Y</button>{/each}
              </div><div class="text-xs" style="margin-top: 6px">Pick one if it's the same person, or carry on for a family member.</div></div></div>
          {/if}
          <div class="grid-3">
            <Field id="np-age" label="Age (years)" required error={errors.np_age_years || errors.patient}>
              {#snippet children({ invalid, describedby })}<input id="np-age" class="input tabular" type="number" min="0" max="130" bind:value={np.age_years} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
            </Field>
            <Field id="np-gender" label="Gender" required error={errors.np_gender}>
              {#snippet children({ invalid, describedby })}
                <select id="np-gender" class="select" bind:value={np.gender} aria-invalid={invalid} aria-describedby={describedby}>
                  <option value="" disabled>Choose…</option><option value="female">Female</option><option value="male">Male</option><option value="other">Other</option>
                </select>
              {/snippet}
            </Field>
            <Field id="np-guardian" label="Guardian (C/O)" error={errors.np_guardian_name}>
              {#snippet children({ invalid, describedby })}<input id="np-guardian" class="input" bind:value={np.guardian_name} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
            </Field>
          </div>
          <Field id="np-address" label="Address" error={errors.np_address}>
            {#snippet children({ invalid, describedby })}<input id="np-address" class="input" bind:value={np.address} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
          </Field>
          <div><button class="link-button" type="button" onclick={() => (addingPatient = false)}>Search existing patients instead</button></div>
        {/if}
      </div>
    </section>

    <section class="card" aria-labelledby="d-title">
      <div class="card-header"><div><h2 class="card-title" id="d-title"><span class="step">2</span> Referred by</h2>
        <p class="card-description">Pick a doctor, type a new name (it's added to your list), or leave it as self.</p></div></div>
      <div class="card-content row" style="align-items: flex-end">
        <div class="grow">
          <Combobox id="doctor" label="Referring doctor" placeholder="Self" icon="stethoscope" search={searchDoctors} bind:value={doctorText}
                    onpick={(d) => { doctor = d; doctorText = d.name; }} emptyText="Not in your list yet: it'll be added when you save.">
            {#snippet option(d)}<span class="font-semibold">{d.name}</span>{#if d.qualification} <span class="text-xs text-muted">{d.qualification}</span>{/if}{/snippet}
          </Combobox>
        </div>
        {#if doctorText}<button class="btn btn-ghost" type="button" onclick={() => { doctorText = ""; doctor = null; }}>Self</button>{/if}
      </div>
    </section>

    <section class="card" aria-labelledby="t-title">
      <div class="card-header"><div><h2 class="card-title" id="t-title"><span class="step">3</span> Tests</h2>
        <p class="card-description">Select a test (or tick several), check the rate, and press Add.</p></div>
        {#if lines.length}<span class="badge badge-info badge-plain">{lines.length} on the bill</span>{/if}</div>
      <div class="card-content stack">
        <div class="test-row">
          <div class="field">
            <label class="label" for="nb-test">Test name</label>
            <TestSelect id="nb-test" bind:picked exclude={onBill} />
          </div>
          <div class="field">
            <label class="label" for="nb-rate">Rate/Price (₹)</label>
            <input id="nb-rate" class="input money" value={picked.length ? pickedPrice.toFixed(2) : ""} readonly />
          </div>
          <button class="btn btn-primary" type="button" onclick={addPicked}><Icon name="plus" /> Add{picked.length > 1 ? ` ${picked.length}` : ""}</button>
        </div>
        {#if errors.lines}<p class="field-error"><Icon name="alert" size="sm" />{errors.lines}</p>{/if}
      </div>
      <div class="card-flush"><div class="table-wrap"><table class="table old-table" style="min-width: 0">
        <thead><tr><th style="width: 46%">Test name</th><th class="num" style="width: 12%">Qty</th><th class="num" style="width: 15%">Unit price</th>
          <th class="num" style="width: 17%">Total price</th><th class="num" style="width: 10%">Action</th></tr></thead>
        <tbody>
          {#each lines as l, i (l.test.id)}
            <tr>
              <td><div class="cell-title">{l.test.name}</div><div class="cell-sub">{l.test.department.name}</div></td>
              <td class="num"><input class="input tabular" style="width: 72px; text-align: right; margin-left: auto" type="number" min="1" max="20" aria-label="Quantity of {l.test.name}" bind:value={l.quantity} /></td>
              <td class="num money">{rupees(l.test.price)}</td>
              <td class="num money font-semibold">{rupees(Number(l.test.price) * l.quantity)}</td>
              <td class="num"><button class="btn btn-ghost-destructive btn-icon btn-sm" type="button" aria-label="Remove {l.test.name}" onclick={() => lines.splice(i, 1)}><Icon name="x" size="sm" /></button></td>
            </tr>
          {:else}
            <tr><td colspan="5" class="text-muted text-sm" style="text-align: center; padding: 18px">No tests added yet.</td></tr>
          {/each}
        </tbody>
        {#if lines.length}<tfoot><tr><td colspan="3" class="num text-muted">Total</td><td class="num money font-semibold">{rupees(subtotal)}</td><td></td></tr></tfoot>{/if}
      </table></div></div>
    </section>

    <section class="card">
      <div class="card-content">
        <Field id="notes" label="Notes on the bill" hint="Optional. Printed on the bill.">
          {#snippet children({ describedby })}<textarea id="notes" class="textarea" style="min-height: 64px" bind:value={notes} aria-describedby={describedby}></textarea>{/snippet}
        </Field>
      </div>
    </section>
  </div>

  <aside class="card summary" aria-labelledby="s-title">
    <div class="card-header"><h2 class="card-title" id="s-title">Summary</h2><span class="text-sm text-muted">{lines.length} {lines.length === 1 ? "test" : "tests"}</span></div>
    <div class="card-content stack">
      <div class="line"><span class="text-muted">Subtotal</span><span class="money">{rupees(subtotal)}</span></div>
      <div class="field">
        <span class="label">Discount</span>
        <div class="row">
          <select class="select" style="width: 128px" aria-label="Discount type" bind:value={discountType}>
            <option value="none">None</option><option value="percent">Percent</option><option value="amount">Amount ₹</option>
          </select>
          {#if discountType !== "none"}
            <input class="input money" type="number" min="0" step={discountType === "percent" ? "1" : "0.01"} max={discountType === "percent" ? 100 : subtotal}
                   aria-label={discountType === "percent" ? "Discount percent" : "Discount amount"} bind:value={discountValue} aria-invalid={!!errors.discount_value} />
          {/if}
        </div>
        {#if errors.discount_value}<p class="field-error"><Icon name="alert" size="sm" />{errors.discount_value}</p>{/if}
      </div>
      {#if discount > 0}<div class="line"><span class="text-muted">Discount</span><span class="money">− {rupees(discount)}</span></div>{/if}
      <div class="line grand"><span>Total</span><span class="money">{rupees(total)}</span></div>

      <hr class="divider" />
      <div class="field">
        <div class="row-between"><label class="label" for="pay-now">Paid now (₹)</label>
          {#if total > 0}<button class="link-button" type="button" onclick={() => (payNow = total.toFixed(2))}>Full amount</button>{/if}</div>
        <div class="row">
          <input id="pay-now" class="input money" type="number" min="0" step="0.01" max={total} placeholder="0" bind:value={payNow} />
          <select class="select" style="width: 140px" aria-label="Paid by" bind:value={payMode}>{#each PAYMENT_MODES as [v, l] (v)}<option value={v}>{l}</option>{/each}</select>
        </div>
        {#if payMode !== "cash" && paying > 0}<input class="input mono" placeholder="UPI / card reference" aria-label="Payment reference" bind:value={payRef} />{/if}
      </div>
      <div class="line {dueAfter > 0 ? 'is-due' : ''}"><span>{dueAfter > 0 ? "Due after this" : "Nothing due"}</span><span class="money">{rupees(dueAfter)}</span></div>
      <label class="check-row"><input class="checkbox" type="checkbox" bind:checked={hold} /> Put the bill on hold</label>
    </div>
    <div class="card-footer card-footer-stack">
      <button class="btn btn-primary btn-lg btn-block" disabled={saving} onclick={() => save(true)}><Icon name="printer" /> {saving ? "Saving…" : "Save and print"}</button>
      <button class="btn btn-outline btn-block" disabled={saving} onclick={() => save(false)}><Icon name="check" /> Save bill</button>
    </div>
  </aside>
</div>

<style>
  .step { display: inline-grid; place-items: center; width: 22px; height: 22px; margin-right: 6px; border-radius: 50%; font-size: 12px;
    background: var(--accent); color: var(--primary-text); vertical-align: 1px; }
  .picked { display: flex; align-items: center; gap: 12px; padding: 12px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--muted); }
  .summary { position: sticky; top: calc(var(--topbar-height) + 16px); }
  .line { display: flex; justify-content: space-between; gap: 12px; font-size: 14px; }
  .line.grand { font-size: 20px; font-weight: 700; font-family: var(--font-heading); }
  .line.is-due { color: var(--destructive); font-weight: 600; }
  .test-row { display: grid; grid-template-columns: minmax(0, 1fr) 170px auto; gap: 12px; align-items: start; }
  .test-row > .btn { margin-top: 25px; }
  .old-table thead th { background: var(--brand-navy); color: #fff; }
  @media (max-width: 900px) { .summary { position: static; } }
  @media (max-width: 560px) { .test-row { grid-template-columns: 1fr; } }
</style>
