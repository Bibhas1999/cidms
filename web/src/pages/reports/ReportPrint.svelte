<script lang="ts">
  import Icon from "../../components/Icon.svelte";
  import { get } from "../../lib/api";
  import type { ReportPrint } from "../../lib/report-types";
  import { tooltip } from "../../lib/tooltip";
  import ReportSheet from "./ReportSheet.svelte";

  // The printable report on A4 (/test-reports/<item>/print). Opens the print dialog by itself once loaded.
  let { params }: { params: Record<string, string> } = $props();

  let data = $state<ReportPrint | null>(null);
  let failed = $state("");

  $effect(() => {
    document.body.classList.add("is-printout");
    return () => document.body.classList.remove("is-printout");
  });

  $effect(() => {
    get<ReportPrint>(`/api/test-reports/for-item/${params.itemId}/print`)
      .then((d) => {
        data = d;
        document.title = `${d.item.test_name} · ${d.item.patient_name}`;
        setTimeout(() => window.print(), 700); // after the logo, signature and QR code have drawn
      })
      .catch((e) => (failed = e.message));
  });
</script>

{#if failed}
  <p class="screen-only" style="padding: 24px">Couldn't load the report: {failed}</p>
{:else if data}
  <div class="screen-only bar">
    <button class="btn btn-primary" onclick={() => window.print()}><Icon name="printer" /> Print</button>
    {#if data.is_final}
      <a class="btn btn-outline" href="/api/test-reports/{data.report_id}/pdf?download=true" use:tooltip={"The same report as a PDF file"}><Icon name="download" /> Download PDF</a>
    {/if}
    <a class="btn btn-outline" href="/test-reports/{data.item.item_id}">Back to the report</a>
  </div>
  <ReportSheet {data} />
{:else}
  <p class="screen-only" style="padding: 24px">Preparing the report…</p>
{/if}

<style>
  :global(body.is-printout) { background: #f3f4f6 !important; }
  .bar { display: flex; gap: 10px; justify-content: center; padding: 16px; }
  @media print { :global(body.is-printout) { background: #fff !important; } .screen-only { display: none !important; } }
</style>
