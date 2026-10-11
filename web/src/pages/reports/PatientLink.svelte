<script lang="ts">
  import Icon from "../../components/Icon.svelte";
  import InfoTip from "../../components/InfoTip.svelte";
  import { api, get, post } from "../../lib/api";
  import { confirmDialog } from "../../lib/confirm.svelte";
  import { date, dateTime } from "../../lib/format";
  import type { Share } from "../../lib/report-types";
  import { notify, notifyError } from "../../lib/toast.svelte";
  import { tooltip } from "../../lib/tooltip";

  // The patient's link to a signed report (the QR code on the printout): its state, and copy / revoke / new.
  let { reportId }: { reportId: string } = $props();

  let share = $state<Share | null>(null);
  let busy = $state(false);

  async function load() {
    try {
      share = await get<Share>(`/api/test-reports/${reportId}/share`);
    } catch (e) {
      notifyError(e);
    }
  }
  $effect(() => { reportId; load(); });

  async function copy() {
    if (!share?.url) return;
    try {
      await navigator.clipboard.writeText(share.url);
      notify("Link copied.");
    } catch {
      notify(share.url, { kind: "info", title: "Copy this link", duration: 0 });
    }
  }

  async function issue() {
    if (share?.active && !(await confirmDialog({ title: "Make a new link?", message: "The current link stops working, including the QR code on reports already printed.",
                                                   confirmLabel: "Make a new link", tone: "danger" }))) return;
    busy = true;
    try {
      share = await post<Share>(`/api/test-reports/${reportId}/share`);
      notify("A new link is ready. Reprint the report so its QR code matches.");
    } catch (e) {
      notifyError(e, { title: "Couldn't make a new link" });
    } finally {
      busy = false;
    }
  }

  async function revoke() {
    if (!(await confirmDialog({ title: "Turn off the patient's link?", message: "The QR code on the printed report will stop working.",
                                confirmLabel: "Turn it off", tone: "danger" }))) return;
    busy = true;
    try {
      share = await api<Share>("DELETE", `/api/test-reports/${reportId}/share`);
      notify("The link is turned off.");
    } catch (e) {
      notifyError(e, { title: "Couldn't turn off the link" });
    } finally {
      busy = false;
    }
  }
</script>

<section class="card" aria-labelledby="link-title">
  <div class="card-header"><div class="row" style="gap: 6px"><h2 class="card-title" id="link-title">Patient link</h2>
    <InfoTip about="Patient link" text="The QR code on the report opens this link. The patient enters the last 4 digits of their mobile number (or year of birth) to see and download the report. Views are counted and logged." /></div>
    {#if share}<span class="badge {share.active ? 'badge-success' : 'badge-plain'}">{share.active ? "Working" : share.exists ? (share.revoked_at ? "Turned off" : "Expired") : "None"}</span>{/if}
  </div>
  <div class="card-content stack-sm">
    {#if !share}
      <p class="text-sm text-muted" aria-busy="true">Loading…</p>
    {:else}
      {#if share.active}
        <div class="row" style="gap: 6px">
          <input class="input mono text-sm" readonly value={share.url} aria-label="Patient link" onfocus={(e) => e.currentTarget.select()} />
          <button class="btn btn-outline btn-icon" type="button" aria-label="Copy link" use:tooltip={"Copy link"} onclick={copy}><Icon name="clipboard" size="sm" /></button>
        </div>
      {/if}
      {#if share.exists}
        <dl class="dl" style="grid-template-columns: 1fr 1fr">
          <div><dt>Views</dt><dd class="tabular">{share.views}{#if share.last_viewed_at} <span class="cell-sub">· last {dateTime(share.last_viewed_at)}</span>{/if}</dd></div>
          <div><dt class="row" style="gap: 4px">{share.active ? "Works until" : "Ended"}<InfoTip about="Expiry" text="Links work for a set number of days after signing (90 unless the centre changed it). Make a new link to start again." /></dt>
            <dd>{date(share.active ? share.expires_at : (share.revoked_at ?? share.expires_at))}</dd></div>
        </dl>
      {/if}
    {/if}
  </div>
  <div class="card-footer">
    {#if share?.active}<button class="btn btn-ghost-destructive btn-sm" type="button" disabled={busy} onclick={revoke}>Turn off</button>{/if}
    <button class="btn btn-outline btn-sm" type="button" disabled={busy} onclick={issue}><Icon name="refresh" size="sm" /> {share?.active ? "New link" : "Make a link"}</button>
  </div>
</section>
