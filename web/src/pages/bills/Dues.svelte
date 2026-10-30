<script lang="ts">
  import DateRange from "../../components/DateRange.svelte";
  import Icon from "../../components/Icon.svelte";
  import PageHeader from "../../components/PageHeader.svelte";
  import Spreadsheet, { type SheetColumn, type SheetRow } from "../../components/Spreadsheet.svelte";
  import { get } from "../../lib/api";
  import { rangeLabel } from "../../lib/dates";
  import { count, rupees } from "../../lib/format";
  import { navigate, router, setQuery } from "../../lib/router.svelte";
  import { session } from "../../lib/session.svelte";
  import { notify, notifyError, toasts } from "../../lib/toast.svelte";
  import { tooltip } from "../../lib/tooltip";

  // Dues: bills still owing, oldest first, grouped by referring doctor. The Summary sheet has one row per
  // doctor; each doctor (and Self) has a sheet of their bills. Double-click a doctor to open their sheet, or a
  // bill to collect its due. /dues?from=&to=&sheet= — dates narrow by bill date (any date by default).
  let { params: _params }: { params?: Record<string, string> } = $props();

  interface Sheet {
    title: string; subtitle: string; columns: SheetColumn[]; rows: SheetRow[]; totals: SheetRow | null;
    summary: { label: string; value: string | number; kind: string }[];
  }
  interface Book extends Sheet { sheets: Sheet[] }

  const q = $derived(router.query);
  const from = $derived(q.get("from") ?? "");
  const to = $derived(q.get("to") ?? "");
  const sheetIndex = $derived(Math.max(0, Number(q.get("sheet") ?? 0) || 0));

  let book = $state<Book | null>(null);
  let loadError = $state("");
  let loading = $state(false);
  let reload = $state(0);

  $effect(() => {
    const ctrl = new AbortController();
    void reload;
    loading = true;
    get<Book>("/api/dues/workbook", { from: from || undefined, to: to || undefined }, ctrl.signal)
      .then((b) => { book = b; loadError = ""; })
      .catch((e) => { if (e.name !== "AbortError") { loadError = e.message; book = null; } })
      .finally(() => { if (!ctrl.signal.aborted) loading = false; });
    return () => ctrl.abort();
  });

  const index = $derived(book ? Math.min(sheetIndex, book.sheets.length) : 0);
  const active = $derived<Sheet | null>(book ? (index > 0 ? book.sheets[index - 1] : book) : null);
  const name = $derived(index > 0 && active ? active.title : "Summary");
  const tabs = $derived(book ? [{ key: "0", title: "Summary", hint: "One row per referring doctor" },
                                ...book.sheets.map((s, i) => ({ key: String(i + 1), title: s.title, hint: `Bills referred by ${s.title} still owing` }))] : []);
  const figures = $derived(book ? book.summary.map((s) => ({ label: s.label, kind: s.kind, value: s.kind === "money" ? rupees(s.value) : s.kind === "int" ? count(Number(s.value)) : String(s.value) })) : []);
  const period = $derived(from || to ? rangeLabel(from, to) : "Any date");

  const openSheet = (key: string) => setQuery({ sheet: key === "0" ? null : key });
  const setRange = (a: string, b: string) => setQuery({ from: a || null, to: b || null, sheet: null });
  /** Switching sheets keeps the dates chosen at the top. */
  function sheetHref(key: string): string {
    const qs = new URLSearchParams();
    if (from) qs.set("from", from);
    if (to) qs.set("to", to);
    if (key !== "0") qs.set("sheet", key);
    const s = qs.toString();
    return `/dues${s ? `?${s}` : ""}`;
  }

  function openRow(row: SheetRow) {
    if (index === 0 && typeof row.doctor === "string" && book) {
      const i = book.sheets.findIndex((s) => s.title === row.doctor);
      if (i >= 0) { openSheet(String(i + 1)); return; }
    }
    if (typeof row.id === "string") navigate(`/bills/${row.id}?collect=1`);
  }

  let downloading = $state(false);
  async function download() {
    downloading = true;
    const progress = notify("Preparing the workbook…", { kind: "progress" });
    try {
      const qs = new URLSearchParams();
      if (from) qs.set("from", from);
      if (to) qs.set("to", to);
      const res = await fetch(`/api/dues/workbook.xlsx${qs.size ? `?${qs}` : ""}`, { credentials: "same-origin" });
      if (!res.ok) throw new Error((await res.json().catch(() => null))?.message ?? `Couldn't prepare the workbook (${res.status}).`);
      const href = URL.createObjectURL(await res.blob());
      const a = Object.assign(document.createElement("a"), { href, download: res.headers.get("Content-Disposition")?.match(/filename="?([^";]+)"?/)?.[1] ?? "dues.xlsx" });
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(href), 30_000);
    } catch (e) {
      notifyError(e, { title: "Download failed" });
    } finally {
      if (progress !== null) toasts.dismiss(progress);
      downloading = false;
    }
  }

  const printedAt = new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata" }).format(new Date());
</script>

<PageHeader eyebrow="Front desk" title="Dues" description="Bills with money still owed today, oldest first, grouped by referring doctor."
            tip="Days owed counts from the bill's date. Summary: one row per referring doctor (bills without one count as Self). Dates, if chosen, narrow by bill date.">
  {#snippet actions()}
    <button class="btn btn-outline" type="button" disabled={!book || loading} onclick={() => window.print()}><Icon name="printer" /> Print</button>
    <button class="btn btn-outline" type="button" disabled={!book || loading || downloading} onclick={download}><Icon name="download" /> {downloading ? "Preparing…" : "Excel"}</button>
  {/snippet}
</PageHeader>

<!-- one bar: the dates, like every other list -->
<section class="card bar no-print" aria-label="Filters">
  <DateRange id="dues" {from} {to} anyLabel="Any date" compact onchange={setRange} />
</section>

<div class="print-head" aria-hidden="true">
  <strong>{session.workspace?.name}</strong> · Dues · {name}{period ? ` · ${period}` : ""} · printed {printedAt}
</div>

{#if loadError}
  <div class="alert alert-destructive" role="alert"><Icon name="alert" /><div>{loadError} <button class="link-button" onclick={() => reload++}>Try again</button></div></div>
{:else}
  <section class="card sheet-card" aria-labelledby="dues-title" aria-busy={loading}>
    <div class="sheet-head">
      <div class="sheet-title">
        <h2 class="card-title" id="dues-title">{name}</h2>
        <span class="text-sm text-muted">{active ? active.subtitle : "Bills still owing"}</span>
      </div>
      {#if figures.length}
        <dl class="figures" aria-live="polite">
          {#each figures as f (f.label)}<div><dt>{f.label}</dt><dd class:money={f.kind === "money"}>{f.value}</dd></div>{/each}
        </dl>
      {/if}
    </div>
    {#if !active}
      <div class="empty" aria-busy="true">Loading…</div>
    {:else if active.rows.length}
      {#key `${index}|${active.subtitle}|${active.rows.length}`}
        <Spreadsheet label={name} columns={active.columns} rows={active.rows} totals={active.totals} height="calc(100vh - 330px)" onopen={openRow} />
      {/key}
      <p class="sheet-hint no-print">{index === 0 ? "Double-click a doctor for their sheet" : "Double-click a bill to collect its due"} · click a heading to sort · Ctrl+C copies into Excel.</p>
    {:else}
      <div class="empty"><Icon name="check" />Nothing owed{from || to ? " for these dates" : ""}.</div>
    {/if}

    <!-- one tab per sheet, at the bottom of the workbook like a real spreadsheet's: Summary, then each referring doctor -->
    <nav class="sheet-tabs no-print" aria-label="Sheets">
      {#each tabs as t (t.key)}
        <a class="sheet-tab" class:is-active={t.key === String(index)} href={sheetHref(t.key)} aria-current={t.key === String(index) ? "page" : undefined}
           use:tooltip={{ text: t.hint, placement: "top" }}>{t.title}</a>
      {/each}
    </nav>
  </section>
{/if}

<style src="./styles/Dues.css"></style>
