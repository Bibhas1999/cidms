<script lang="ts">
  import { z } from "zod";
  import Field from "../../components/Field.svelte";
  import FormErrors from "../../components/FormErrors.svelte";
  import Icon from "../../components/Icon.svelte";
  import { ApiError, get, post } from "../../lib/api";
  import { Form } from "../../lib/form.svelte";
  import type { ReportPrint } from "../../lib/report-types";
  import ReportSheet from "./ReportSheet.svelte";

  // The patient's page for a signed report, opened from the QR code (/r/<token>). No sign-in: it first asks for
  // the last 4 digits of the patient's mobile (or the year of birth), and shows nothing but the centre's name and
  // logo until that matches. The PDF download works for 15 minutes after that.
  let { params }: { params: Record<string, string> } = $props();

  type Info = { centre_name: string; has_logo: boolean; check: "mobile" | "birth_year" | "bill" };
  let info = $state<Info | null>(null);
  let missing = $state("");
  let report = $state<ReportPrint | null>(null);
  let pdfUrl = $state("");

  // Not for search engines, and the link never leaks in a Referer header.
  $effect(() => {
    const metas = [["robots", "noindex, nofollow"], ["referrer", "no-referrer"]].map(([name, content]) => {
      const m = document.createElement("meta");
      m.name = name;
      m.content = content;
      document.head.appendChild(m);
      return m;
    });
    document.body.classList.add("is-printout");
    return () => { metas.forEach((m) => m.remove()); document.body.classList.remove("is-printout"); };
  });

  $effect(() => {
    get<Info>(`/api/public/reports/${encodeURIComponent(params.token)}`)
      .then((i) => { info = i; document.title = `Your report · ${i.centre_name}`; })
      .catch((e) => (missing = e.message));
  });

  const QUESTION = {
    mobile: ["Last 4 digits of your mobile number", "The mobile number given at the centre when the test was booked."],
    birth_year: ["Your year of birth", "Four digits, for example 1985."],
    bill: ["Last 4 digits of your bill number", "Printed at the top of your bill, e.g. …/000123 → 0123."],
  } as const;

  const form = new Form({
    schema: z.object({ check: z.string().trim().regex(/^\d{4}$/, "Enter 4 digits.") }),
    initial: { check: "" },
    onSubmit: async ({ check }) => {
      const res = await post<{ report: ReportPrint; pdf_url: string }>(`/api/public/reports/${encodeURIComponent(params.token)}/open`, { check });
      report = res.report;
      pdfUrl = res.pdf_url;
    },
  });
  let tries = $state("");
  async function open(e: Event) {
    tries = "";
    try {
      await form.submit(e);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) missing = err.message;
      else if (err instanceof ApiError && !Object.keys(err.fieldErrors).length) tries = err.message;
    }
  }
</script>

{#if report}
  <div class="screen-only bar">
    <a class="btn btn-primary" href={pdfUrl} rel="noreferrer"><Icon name="download" /> Download PDF</a>
    <button class="btn btn-outline" onclick={() => window.print()}><Icon name="printer" /> Print</button>
  </div>
  <ReportSheet data={report} />
{:else}
  <main class="gate">
    <div class="card gate-card">
      {#if missing}
        <div class="card-content stack">
          <h1 class="gate-title">This link doesn't work</h1>
          <p class="text-muted">{missing}</p>
        </div>
      {:else if !info}
        <div class="empty" aria-busy="true">Loading…</div>
      {:else}
        <form class="card-content stack" onsubmit={open} novalidate>
          {#if info.has_logo}<img class="gate-logo" src="/api/workspace/logo" alt="" />{/if}
          <div>
            <p class="eyebrow">{info.centre_name}</p>
            <h1 class="gate-title">Your test report</h1>
            <p class="text-sm text-muted">To keep your report private, please confirm who you are.</p>
          </div>
          <FormErrors {form} labels={{ check: QUESTION[info.check][0] }} />
          {#if tries}<div class="alert alert-destructive" role="alert"><Icon name="alert" />{tries}</div>{/if}
          <Field id="check" label={QUESTION[info.check][0]} required error={form.error("check")} tip={QUESTION[info.check][1]}>
            {#snippet children({ invalid, describedby })}
              <input id="check" class="input tabular" inputmode="numeric" autocomplete="off" maxlength="4" bind:value={form.values.check}
                     {...form.field("check")} aria-invalid={invalid} aria-describedby={describedby} />
            {/snippet}
          </Field>
          <button class="btn btn-primary btn-block" type="submit" disabled={form.submitting}>{form.submitting ? "Checking…" : "Show my report"}</button>
        </form>
      {/if}
    </div>
  </main>
{/if}

<style>
  :global(body.is-printout) { background: #f3f4f6 !important; }
  .bar { display: flex; gap: 10px; justify-content: center; padding: 16px; flex-wrap: wrap; }
  .gate { min-height: 100vh; display: grid; place-items: center; padding: 16px; }
  .gate-card { width: 100%; max-width: 400px; }
  .gate-title { font-size: 20px; margin: 2px 0 4px; }
  .gate-logo { max-height: 56px; max-width: 160px; object-fit: contain; align-self: flex-start; }
  @media print { .screen-only { display: none !important; } :global(body.is-printout) { background: #fff !important; } }
</style>
