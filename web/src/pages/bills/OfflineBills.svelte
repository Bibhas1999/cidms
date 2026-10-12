<script lang="ts">
  import Icon from "../../components/Icon.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import { confirmDialog } from "../../lib/confirm.svelte";
  import { connection } from "../../lib/connection.svelte";
  import { dateTime, rupees } from "../../lib/format";
  import { offline, type OfflineBill } from "../../lib/offline.svelte";
  import { router } from "../../lib/router.svelte";
  import { notifyError } from "../../lib/toast.svelte";
  import { tooltip } from "../../lib/tooltip";

  // Bills made on this computer while CIDMS couldn't be reached: waiting to go, sent (with their final number,
  // kept here a week to reprint), or needing a look (CIDMS couldn't take them as they are, and says why).
  $effect(() => { void offline.reload(); });
  const made = router.query.get("made");

  const printUrl = (b: OfflineBill) => (b.status === "sent" && b.sent?.id ? `/bills/${b.sent.id}/print` : `/bills/offline/${b.id}/print`);

  async function retry(b: OfflineBill, acceptNewTotal = false) {
    try { await offline.retry(b, { acceptNewTotal }); } catch (e) { notifyError(e, { title: "Couldn't send the bill" }); }
  }

  async function discard(b: OfflineBill) {
    const ok = await confirmDialog({
      title: `Discard ${b.offline_no}?`, tone: "danger", confirmLabel: "Discard the bill",
      message: `${b.bill.patient_name}, ${rupees(b.bill.total)}${Number(b.bill.paid) > 0 ? `, ${rupees(b.bill.paid)} paid` : ""}. It was never sent to CIDMS, so it's gone for good. If money was taken, make the bill again.`,
    });
    if (ok) await offline.discard(b);
  }
</script>

<PageHeader eyebrow="Front desk" title="Offline bills"
            description="Bills made on this computer while CIDMS couldn't be reached. They're sent by themselves, oldest first, as soon as the connection is back.">
  {#snippet actions()}
    <button class="btn btn-primary" type="button" onclick={() => offline.send()} disabled={!connection.usable || offline.sending || !offline.waiting}
            use:tooltip={connection.usable ? "Send waiting bills now" : "Waiting for the connection"}>
      <Icon name="refresh" size="sm" />{offline.sending ? "Sending…" : "Send now"}
    </button>
  {/snippet}
</PageHeader>

{#if !connection.usable}
  <div class="alert alert-warning mb" role="status"><Icon name="alert" /><div><div class="alert-title">Offline</div>
    The bills below go to CIDMS by themselves when the connection is back. Keep this computer on; you can carry on billing.</div></div>
{/if}

<section class="card">
  <div class="table-wrap">
    <table class="table" style="min-width: 0">
      <thead><tr><th>Bill</th><th>Patient</th><th class="num">Total</th><th>Status</th><th class="num"><span class="sr-only">Actions</span></th></tr></thead>
      <tbody>
        {#each offline.bills as b (b.id)}
          <tr class:is-new={b.id === made}>
            <td><div class="cell-title mono">{b.sent?.invoice_no || b.offline_no}</div>
              <div class="cell-sub">{b.sent?.invoice_no ? `made offline as ${b.offline_no} · ` : ""}{dateTime(b.made_at)}</div></td>
            <td><div class="cell-title">{b.bill.patient_name}</div><div class="cell-sub">{b.bill.items.map((i) => i.test_name).join(", ")}</div></td>
            <td class="num"><div class="tabular font-semibold">{rupees(b.bill.total)}</div>
              {#if Number(b.bill.due) > 0}<div class="cell-sub money-due">{rupees(b.bill.due)} due</div>{/if}</td>
            <td>
              {#if b.status === "sent"}<span class="badge badge-success"><Icon name="check" size="sm" />In CIDMS</span>
              {:else if b.status === "waiting"}<span class="badge badge-info"><Icon name="clock" size="sm" />{offline.sending ? "Sending" : "Waiting"}</span>
              {:else}<span class="badge badge-destructive"><Icon name="alert" size="sm" />Needs a look</span>
                <div class="cell-sub why">{b.error}</div>{/if}
            </td>
            <td class="num">
              <div class="acts">
                <a class="btn btn-ghost btn-sm" href={printUrl(b)} target="_blank" rel="noopener"
                   use:tooltip={b.status === "sent" ? "Print with the final bill number" : "Print the provisional bill"}><Icon name="printer" size="sm" />Print</a>
                {#if b.status === "sent" && b.sent?.id}<a class="btn btn-ghost btn-sm" href="/bills/{b.sent.id}">Open</a>{/if}
                {#if b.status === "attention"}
                  {#if b.error_field === "offline_total"}
                    <button class="btn btn-outline btn-sm" type="button" disabled={!connection.usable} onclick={() => retry(b, true)}>Save at today's prices</button>
                  {:else}
                    <button class="btn btn-outline btn-sm" type="button" disabled={!connection.usable} onclick={() => retry(b)}>Try again</button>
                  {/if}
                {/if}
                {#if b.status !== "sent"}
                  <button class="btn btn-ghost btn-icon btn-sm" type="button" aria-label="Discard {b.offline_no}" use:tooltip={"Discard this bill"}
                          onclick={() => discard(b)}><Icon name="trash" size="sm" /></button>
                {/if}
              </div>
            </td>
          </tr>
        {:else}
          <tr><td colspan="5"><div class="empty"><Icon name="inbox" />No offline bills on this computer.</div></td></tr>
        {/each}
      </tbody>
    </table>
  </div>
</section>

<style>
  .mb { margin-bottom: 16px; }
  .acts { display: inline-flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
  .why { max-width: 320px; white-space: normal; color: var(--destructive); }
  tr.is-new td { background: color-mix(in srgb, var(--primary) 7%, transparent); }
</style>
