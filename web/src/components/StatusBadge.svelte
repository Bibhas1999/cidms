<script lang="ts">
  import { BILL_STATUS, billBadge, LINE_STATUS, PAYMENT_HELP, paymentState } from "../lib/bill-types";
  import { tooltip as tip } from "../lib/tooltip";

  // Every status pill in the app, so the same state always has the same colour and words:
  //   <StatusBadge bill={b} />               on hold / cancelled, else Paid · Part paid · Unpaid
  //   <StatusBadge payment={b} />            Paid · Part paid · Unpaid · Cancelled
  //   <StatusBadge billStatus="on_hold" />   Confirmed · On hold · Cancelled
  //   <StatusBadge line="scanned" />         a test's progress: Waiting · Scanned · Reported · Delivered · Taken off
  //   <StatusBadge active={t.is_active} />   Active · Switched off (offLabel to change the words)
  //   <StatusBadge tone="warning" label="Temporary password" />
  // The badge explains itself in a tooltip where the words alone might not.
  type Money = { total: string; paid: string; due: string; status: string };
  let { bill, payment, billStatus, line, active, onLabel = "Active", offLabel = "Switched off", tone, label, help = "" }: {
    bill?: Money; payment?: Money; billStatus?: string; line?: string; active?: boolean; onLabel?: string; offLabel?: string;
    tone?: "success" | "warning" | "destructive" | "info" | "navy"; label?: string; help?: string;
  } = $props();

  const pair = $derived.by((): [string, string] => {
    if (bill) return billBadge(bill);
    if (payment) return paymentState(payment);
    if (billStatus) return BILL_STATUS[billStatus] ?? ["badge-info", billStatus];
    if (line) return LINE_STATUS[line] ?? ["badge-info", line];
    if (active !== undefined) return active ? ["badge-success", onLabel] : ["badge-destructive", offLabel];
    return [`badge-${tone ?? "info"}`, label ?? ""];
  });
  const hint = $derived(help || PAYMENT_HELP[pair[1]] || "");
</script>

<span class="badge {pair[0]} status-badge" use:tip={hint}>{pair[1]}</span>

<style>
  .status-badge { white-space: nowrap; }
</style>
