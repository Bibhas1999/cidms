<script lang="ts">
  import QRCode from "qrcode";
  import BillSheet from "./BillSheet.svelte";
  import { get, post } from "../../lib/api";
  import type { Bill, Patient } from "../../lib/bill-types";
  import { cachedSettings, getOfflineBill } from "../../lib/offline.svelte";
  import type { CentreSettings } from "../../lib/types";

  // The printed bill (BillSheet.svelte has the layout). Opens the print dialog by itself.
  // /bills/offline/<id>/print: a bill made offline, from this computer (provisional number, no QR yet).
  let { params }: { params: Record<string, string> } = $props();
  const offlineId = $derived(params.offlineId ?? "");

  let bill = $state<Bill | null>(null);
  let centre = $state<CentreSettings | null>(null);
  let patientNo = $state("");
  let qr = $state("");
  let failed = $state("");

  $effect(() => {
    document.body.classList.add("is-printout");
    return () => document.body.classList.remove("is-printout");
  });

  $effect(() => {
    if (!offlineId) return;
    Promise.all([getOfflineBill(offlineId), get<CentreSettings>("/api/settings").catch(() => cachedSettings())])
      .then(([o, c]) => {
        if (!o || !c) { failed = "This offline bill isn't on this computer."; return; }
        bill = o.bill;
        centre = c;
        patientNo = o.patient_no;
        document.title = `${o.offline_no} · ${o.bill.patient_name}`;
        setTimeout(() => window.print(), 500);
      })
      .catch((e) => (failed = e.message));
  });

  $effect(() => {
    if (offlineId) return;
    Promise.all([get<Bill>(`/api/bills/${params.id}`), get<CentreSettings>("/api/settings")])
      .then(async ([b, c]) => {
        bill = b;
        centre = c;
        document.title = `${b.invoice_no} · ${b.patient_name}`;
        get<Patient>(`/api/patients/${b.patient_id}`).then((p) => (patientNo = p.patient_no)).catch(() => {});
        // The patient's own public page (a check first: mobile/birth year/bill number), not the staff one.
        try {
          const share = await post<{ url: string }>(`/api/bills/${b.id}/share`);
          qr = await QRCode.toDataURL(share.url, { margin: 0, width: 140 });
        } catch { /* no QR if the link couldn't be issued; the rest of the bill still prints */ }
        setTimeout(() => window.print(), 500);
      })
      .catch((e) => (failed = e.message));
  });
</script>

{#if failed}
  <p class="screen-only" style="padding: 24px">Couldn't load the bill: {failed}</p>
{:else if bill && centre}
  <div class="screen-only bar">
    <button class="btn btn-primary" onclick={() => window.print()}>Print</button>
    <a class="btn btn-outline" href={offlineId ? "/bills/offline" : `/bills/${bill.id}`}>Back to the bill</a>
  </div>
  <BillSheet {bill} {centre} {patientNo} {qr} provisional={!!offlineId} />
{:else}
  <p class="screen-only" style="padding: 24px">Preparing the bill…</p>
{/if}

<style src="./styles/BillPrint.css"></style>
