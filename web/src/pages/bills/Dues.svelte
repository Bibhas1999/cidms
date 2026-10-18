<script lang="ts">
  import DateRange from "../../components/DateRange.svelte";
  import Icon from "../../components/Icon.svelte";
  import Spreadsheet, { type SheetColumn, type SheetRow } from "../../components/Spreadsheet.svelte";
  import Workbook from "../../components/Workbook.svelte";
  import { get } from "../../lib/api";
  import { rangeLabel } from "../../lib/dates";
  import { count, rupees } from "../../lib/format";
  import { navigate, router, setQuery } from "../../lib/router.svelte";
  import { session } from "../../lib/session.svelte";
  import { notify, notifyError, toasts } from "../../lib/toast.svelte";

  // Dues, as a workbook: bills still owing, oldest first. The Summary sheet has one row per referring doctor;
  // each doctor (and Self) has a sheet of their bills. Double-click a doctor to open their sheet, or a bill to
  // collect its due. /dues?from=&to=&sheet= — dates narrow by bill date (any date by default).
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
  const tabs = $derived(book ? [{ key: "0", label: "Summary", hint: "One row per referring doctor" },
                                ...book.sheets.map((s, i) => ({ key: String(i + 1), label: s.title, hint: `Bills referred by ${s.title} still owing` }))] : []);
  const figures = $derived(book ? book.summary.map((s) => ({ label: s.label, value: s.kind === "money" ? rupees(s.value) : s.kind === "int" ? count(Number(s.value)) : String(s.value) })) : []);
  const period = $derived(from || to ? rangeLabel(from, to) : "Any date");

  const openSheet = (key: string) => setQuery({ sheet: key === "0" ? null : key });
  const setRange = (a: string, b: string) => setQuery({ from: a || null, to: b || null, sheet: null });

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
</script>

<Workbook title="Dues" file={`${session.workspace?.name ?? ""} · ${period}`} sheets={tabs} active={String(index)} onsheet={openSheet}
          nameBox={name} formula={active ? active.subtitle : "Bills still owing"}
          about="Bills with money still owed today, oldest first. Days owed counts from the bill's date. Summary: one row per referring doctor (bills without one count as Self). Dates, if chosen, narrow by bill date."
          {figures} status={loading ? "Calculating…" : loadError ? "Error" : "Ready"}
          hint={index === 0 ? "Double-click a doctor for their sheet · click a heading to sort · Ctrl+C copies" : "Double-click a bill to collect its due · click a heading to sort · Ctrl+C copies"}>
  {#snippet actions()}
    <button class="btn btn-sm" type="button" disabled={!book || loading} onclick={() => window.print()}><Icon name="printer" size="sm" /> Print</button>
    <button class="btn btn-sm" type="button" disabled={!book || loading || downloading} onclick={download}><Icon name="download" size="sm" /> {downloading ? "Preparing…" : "Excel"}</button>
  {/snippet}
  {#snippet ribbon()}
    <div class="rb-group"><div class="rb-body"><DateRange id="dues" {from} {to} anyLabel="Any date" compact onchange={setRange} /></div><span class="rb-label">Bill dates</span></div>
  {/snippet}

  {#if loadError}
    <div class="wb-empty" role="alert"><Icon name="alert" />{loadError} <button class="link-button" onclick={() => reload++}>Try again</button></div>
  {:else if !active}
    <div class="wb-empty" aria-busy="true">Loading…</div>
  {:else if active.rows.length}
    {#key `${index}|${active.subtitle}|${active.rows.length}`}
      <Spreadsheet label={name} columns={active.columns} rows={active.rows} totals={active.totals} height="calc(100vh - 318px)" onopen={openRow} />
    {/key}
  {:else}
    <div class="wb-empty"><Icon name="check" />Nothing owed{from || to ? " for these dates" : ""}.</div>
  {/if}
</Workbook>
