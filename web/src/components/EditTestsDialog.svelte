<script lang="ts">
  import { ApiError, put } from "../lib/api";
  import type { Bill, BillLine, LabTest } from "../lib/bill-types";
  import { rupees } from "../lib/format";
  import { notify, notifyError } from "../lib/toast.svelte";
  import TestPicker from "./TestPicker.svelte";
  import Dialog from "./Dialog.svelte";
  import Field from "./Field.svelte";
  import Icon from "./Icon.svelte";

  // Add more tests to a saved bill, or take off tests not started yet. The server prices new tests from the
  // catalogue, keeps the old tests at the price they were billed at, and records the reason.
  let { open = $bindable(false), bill, onsaved }: { open?: boolean; bill: Bill; onsaved: (b: Bill) => void } = $props();

  interface Row { line?: BillLine; test?: LabTest; quantity: number }
  let rows = $state<Row[]>([]);
  let reason = $state("");
  let errors = $state<Record<string, string>>({});
  let saving = $state(false);

  $effect(() => {
    if (open) {
      rows = bill.items.filter((l) => l.status !== "cancelled").map((l) => ({ line: l, quantity: l.quantity }));
      reason = ""; errors = {};
    }
  });

  const testId = (r: Row) => r.line?.test_id ?? r.test?.id ?? "";
  const selected = $derived(new Set(rows.map(testId)));
  // Tests already scanned, reported or delivered stay on the bill.
  const locked = $derived(new Set(rows.filter((r) => r.line && r.line.status !== "billed").map(testId)));

  function toggle(t: LabTest, on: boolean) {
    if (on && !selected.has(t.id)) {
      // Ticking a test that was on the bill before brings that line back (at the price it was billed at).
      const before = bill.items.find((l) => l.test_id === t.id && l.status !== "cancelled");
      rows.push(before ? { line: before, quantity: before.quantity } : { test: t, quantity: 1 });
    }
    if (!on) rows = rows.filter((r) => testId(r) !== t.id || locked.has(t.id));
  }

  function addMany(tests: LabTest[]) {
    for (const t of tests) toggle(t, true);
  }

  const price = (r: Row) => Number(r.line ? r.line.unit_price : r.test!.price);
  const subtotal = $derived(rows.reduce((s, r) => s + price(r) * r.quantity, 0));
  const added = $derived(rows.filter((r) => r.test).length);
  const removed = $derived(bill.items.filter((l) => l.status !== "cancelled" && !rows.some((r) => r.line?.id === l.id)).length);

  async function save() {
    errors = {};
    saving = true;
    try {
      const updated = await put<Bill>(`/api/bills/${bill.id}`, {
        referring_doctor_id: bill.referring_doctor_id, referring_doctor_name: bill.referring_doctor_id ? "" : bill.referring_doctor_name,
        lines: rows.map((r) => (r.line ? { id: r.line.id, quantity: r.quantity } : { test_id: r.test!.id, quantity: r.quantity })),
        discount_type: bill.discount_type, discount_value: bill.discount_value, notes: bill.notes, reason,
      });
      open = false;
      notify(`New total ${rupees(updated.total)}${Number(updated.due) > 0 ? `, ${rupees(updated.due)} due` : ""}.`, { title: "Tests changed" });
      onsaved(updated);
    } catch (e) {
      if (e instanceof ApiError && Object.keys(e.fieldErrors).length) errors = e.fieldErrors;
      else notifyError(e, { title: "Couldn't change the tests" });
    } finally {
      saving = false;
    }
  }
</script>

<Dialog bind:open title="Change tests on {bill.invoice_no}" icon="flask" tone="info" wide
        description="Add more tests, or take off tests that haven't been started. Tests already on the bill keep the price they were billed at.">
  <div class="stack">
    <TestPicker {selected} {locked} ontoggle={toggle} onaddmany={addMany} />
    {#if errors.lines}<p class="field-error"><Icon name="alert" size="sm" />{errors.lines}</p>{/if}
    <div class="table-wrap"><table class="table" style="min-width: 0">
      <thead><tr><th>Test</th><th class="num">Price</th><th class="num" style="width: 100px">Qty</th><th class="num">Amount</th><th><span class="sr-only">Remove</span></th></tr></thead>
      <tbody>
        {#each rows as r, i (r.line?.id ?? r.test?.id)}
          {@const started = !!r.line && r.line.status !== "billed"}
          <tr>
            <td><div class="cell-title">{r.line?.test_name ?? r.test?.name}
              {#if r.test}<span class="badge badge-success badge-plain" style="height: 20px">New</span>{/if}</div>
              <div class="cell-sub">{r.line?.department_name ?? r.test?.department.name}{#if started} · already {r.line?.status}{/if}</div></td>
            <td class="num money">{rupees(price(r))}</td>
            <td class="num"><input class="input input-sm tabular" style="width: 70px; text-align: right" type="number" min="1" max="20"
                                   aria-label="Quantity" bind:value={r.quantity} disabled={started} /></td>
            <td class="num money">{rupees(price(r) * r.quantity)}</td>
            <td class="num">
              {#if !started}<button class="btn btn-ghost-destructive btn-icon btn-sm" aria-label="Take off {r.line?.test_name ?? r.test?.name}" onclick={() => rows.splice(i, 1)}><Icon name="x" size="sm" /></button>{/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table></div>
    <div class="row-between text-sm">
      <span class="text-muted">{added} added · {removed} taken off</span>
      <span>New subtotal <strong class="money">{rupees(subtotal)}</strong> <span class="text-muted">(before any discount)</span></span>
    </div>
    <Field id="edit-reason" label="Reason for the change" required error={errors.reason} hint="Kept in the bill's history, e.g. Doctor added a USG.">
      {#snippet children({ invalid, describedby })}<input id="edit-reason" class="input" bind:value={reason} aria-invalid={invalid} aria-describedby={describedby} />{/snippet}
    </Field>
  </div>
  {#snippet footer()}
    <button class="btn btn-outline" type="button" onclick={() => (open = false)}>Cancel</button>
    <button class="btn btn-primary" type="button" disabled={saving || !rows.length || reason.trim().length < 3 || (!added && !removed && rows.every((r) => !r.line || r.quantity === r.line.quantity))}
            onclick={save}><Icon name="check" /> {saving ? "Saving…" : "Save changes"}</button>
  {/snippet}
</Dialog>
