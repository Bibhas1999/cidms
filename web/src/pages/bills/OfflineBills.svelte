<script lang="ts">
  import Icon from "../../components/Icon.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import { confirmDialog } from "../../lib/confirm.svelte";
  import { connection } from "../../lib/connection.svelte";
  import { dateTime, rupees } from "../../lib/format";
  import { offline, refreshOfflineData, type OfflineBill } from "../../lib/offline.svelte";
  import { outbox, type OutboxItem } from "../../lib/outbox.svelte";
  import { copyCount, forgetCopies } from "../../lib/response-cache.svelte";
  import { persistStorage } from "../../lib/vault";
  import { router } from "../../lib/router.svelte";
  import { notify, notifyError } from "../../lib/toast.svelte";
  import { tooltip } from "../../lib/tooltip";

  // Bills made on this computer while CIDMS couldn't be reached: waiting to go, sent (with their final number,
  // kept here a week to reprint), or needing a look (CIDMS couldn't take them as they are, and says why).
  $effect(() => { void offline.reload(); void outbox.reload(); void loadStorage(); });

  // ---------- what this computer keeps ----------
  let copies = $state(0);
  let used = $state<number | null>(null);
  let quota = $state<number | null>(null);
  let persisted = $state(false);
  let refreshing = $state(false);
  async function loadStorage() {
    copies = await copyCount();
    try {
      const e = await navigator.storage?.estimate?.();
      used = e?.usage ?? null; quota = e?.quota ?? null;
      persisted = (await navigator.storage?.persisted?.()) ?? false;
    } catch { /* not offered */ }
  }
  const mb = (n: number) => (n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`);
  async function refreshNow() {
    refreshing = true;
    await refreshOfflineData();
    refreshing = false;
    await loadStorage();
    notify("Tests, prices, doctors and recent patients are saved as of now.");
  }
  async function clearCopies() {
    if (!(await confirmDialog({ title: "Clear the saved screens?", confirmLabel: "Clear", tone: "danger",
                                message: "The copies of screens you've opened go from this computer. Bills and payments waiting to be sent are kept." }))) return;
    await forgetCopies();
    await loadStorage();
    notify("Saved screens cleared from this computer.");
  }
  async function keep() {
    persisted = await persistStorage();
    notify(persisted ? "The browser will keep these even when space runs low." : "The browser didn't agree; it may clear them if space runs low.",
           { kind: persisted ? "success" : "warning" });
  }
  async function discardChange(i: OutboxItem) {
    if (await confirmDialog({ title: "Discard this payment?", tone: "danger", confirmLabel: "Discard",
                              message: `${i.label}. It was never sent to CIDMS, so it's gone for good.` })) await outbox.discard(i);
  }
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

<PageHeader eyebrow="Front Desk" title="Offline"
            description="What this computer keeps for working without the internet: bills and payments made offline (sent by themselves, oldest first, as soon as the connection is back) and saved copies of the screens you've opened.">
  {#snippet actions()}
    <button class="btn btn-primary" type="button" onclick={() => { void offline.send(); void outbox.send(); }}
            disabled={!connection.usable || offline.sending || outbox.sending || (!offline.waiting && !outbox.waiting)}
            use:tooltip={connection.usable ? "Send waiting bills now" : "Waiting for the connection"}>
      <Icon name="refresh" size="sm" />{offline.sending ? "Sending…" : "Send now"}
    </button>
  {/snippet}
</PageHeader>

{#if !connection.usable}
  <div class="alert alert-warning mb" role="status"><Icon name="alert" /><div><div class="alert-title">Offline</div>
    The bills below go to CIDMS by themselves when the connection is back. Keep this computer on; you can carry on billing.</div></div>
{/if}

<section class="card mb" aria-labelledby="kept-title">
  <div class="card-header"><div><h2 class="card-title" id="kept-title">Saved on this computer</h2>
    <p class="card-description">Encrypted; removed when you sign out (except bills and payments not yet sent).</p></div></div>
  <div class="card-content kept">
    <div><div class="text-sm text-muted">Screens saved</div><div class="font-semibold">{copies}</div></div>
    <div><div class="text-sm text-muted">Offline bills</div><div class="font-semibold">{offline.bills.length}</div></div>
    <div><div class="text-sm text-muted">Payments waiting</div><div class="font-semibold">{outbox.waiting}</div></div>
    <div><div class="text-sm text-muted">Space used</div><div class="font-semibold">{used !== null ? `${mb(used)}${quota ? ` of ${mb(quota)}` : ""}` : "—"}</div></div>
    <div><div class="text-sm text-muted">Catalogue saved</div><div class="font-semibold">{offline.readyAt ? dateTime(offline.readyAt) : "Not yet"}</div></div>
    <div><div class="text-sm text-muted">Kept when space is low</div><div class="font-semibold">{persisted ? "Yes" : "Not guaranteed"}</div></div>
  </div>
  <div class="card-footer">
    <button class="btn btn-outline btn-sm" type="button" disabled={!connection.usable || refreshing} onclick={refreshNow}><Icon name="refresh" size="sm" />{refreshing ? "Saving…" : "Save the catalogue now"}</button>
    {#if !persisted}<button class="btn btn-outline btn-sm" type="button" onclick={keep}><Icon name="lock" size="sm" />Keep it when space is low</button>{/if}
    <button class="btn btn-ghost-destructive btn-sm" type="button" disabled={!copies} onclick={clearCopies}><Icon name="trash" size="sm" />Clear saved screens</button>
  </div>
</section>

{#if outbox.items.length}
  <section class="card mb" aria-labelledby="changes-title">
    <div class="card-header"><div><h2 class="card-title" id="changes-title">Payments made offline</h2></div></div>
    <div class="table-wrap">
      <table class="table" style="min-width: 0">
        <thead><tr><th>What</th><th>Made</th><th>Status</th><th class="num"><span class="sr-only">Actions</span></th></tr></thead>
        <tbody>
          {#each outbox.items as i (i.id)}
            <tr>
              <td><a class="cell-title" href={i.link}>{i.label}</a></td>
              <td class="text-sm nowrap">{dateTime(i.made_at)}</td>
              <td>
                {#if i.status === "sent"}<span class="badge badge-success"><Icon name="check" size="sm" />In CIDMS</span>
                {:else if i.status === "waiting"}<span class="badge badge-info"><Icon name="clock" size="sm" />{outbox.sending ? "Sending" : "Waiting"}</span>
                {:else}<span class="badge badge-destructive"><Icon name="alert" size="sm" />Needs a look</span><div class="cell-sub why">{i.error}</div>{/if}
              </td>
              <td class="num"><div class="acts">
                {#if i.status === "attention"}<button class="btn btn-outline btn-sm" type="button" disabled={!connection.usable} onclick={() => outbox.retry(i)}>Try again</button>{/if}
                {#if i.status !== "sent"}<button class="btn btn-ghost btn-icon btn-sm" type="button" aria-label="Discard" use:tooltip={"Discard this payment"} onclick={() => discardChange(i)}><Icon name="trash" size="sm" /></button>{/if}
              </div></td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </section>
{/if}

<section class="card" aria-label="Offline bills">
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

<style src="./styles/OfflineBills.css"></style>
