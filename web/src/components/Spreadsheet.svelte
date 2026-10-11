<script lang="ts" module>
  export type SheetKind = "text" | "money" | "int" | "date" | "datetime" | "percent";
  export interface SheetColumn { key: string; label: string; kind: SheetKind; width?: number }
  export type SheetRow = Record<string, string | number | null | undefined>;
</script>

<script lang="ts">
  import jspreadsheet from "jspreadsheet-ce";
  import "jsuites/dist/jsuites.css";
  import "jspreadsheet-ce/dist/jspreadsheet.css";
  import { count, date, dateTime } from "../lib/format";

  // A read-only, Excel-style sheet (Jspreadsheet CE, MIT): column letters and row numbers, gridlines, sort by
  // clicking a heading, a filter on every column, resizable columns, select cells and copy them into Excel
  // (Ctrl+C). Numbers stay numbers, so they sort properly; they're only shown as ₹ 1,23,456.00 / 12.50%.
  // Formulas are off: nothing typed into a bill (say a name starting with "=") can ever run as one.
  //   <Spreadsheet columns={…} rows={…} totals={…} height="calc(100vh - 320px)" onopen={(row) => …} />
  let { columns, rows, totals = null, height = "520px", onopen, label = "Report" }: {
    columns: SheetColumn[]; rows: SheetRow[]; totals?: SheetRow | null; height?: string;
    /** Double-click a row (or press Enter on it) to open it, e.g. the bill. */
    onopen?: (row: SheetRow) => void;
    label?: string;
  } = $props();

  let host: HTMLDivElement;

  const inr2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const numeric = (k: SheetKind) => k === "money" || k === "int" || k === "percent";

  function shown(v: unknown, kind: SheetKind): string {
    if (v === null || v === undefined || v === "") return "";
    switch (kind) {
      case "money": return `₹ ${inr2.format(Number(v))}`;
      case "int": return count(Number(v));
      case "percent": return `${Number(v).toFixed(2)}%`;
      case "date": return date(String(v));
      case "datetime": return dateTime(String(v));
      default: return String(v);
    }
  }
  // What the sheet holds (and sorts and filters by): real numbers, ISO dates (which sort as text), text.
  const raw = (v: unknown, kind: SheetKind) =>
    v === null || v === undefined ? "" : numeric(kind) ? Number(v) : String(v);

  function widthFor(c: SheetColumn): number {
    if (c.width) return c.width;
    if (c.kind === "money") return 130;
    if (c.kind === "int" || c.kind === "percent") return 90;
    if (c.kind === "date") return 120;
    if (c.kind === "datetime") return 160;
    const longest = Math.max(c.label.length, ...rows.slice(0, 200).map((r) => String(r[c.key] ?? "").length));
    return Math.min(320, Math.max(110, longest * 7.5 + 24));
  }

  $effect(() => {
    // Rebuild when the report changes (columns, rows or totals).
    const cols = columns, data = rows, foot = totals;
    if (!host) return;
    const sheets = jspreadsheet(host, {
      tabs: false, toolbar: false, about: false, parseFormulas: false,
      contextMenu: () => false,
      worksheets: [{
        worksheetName: label,
        data: data.map((r) => cols.map((c) => raw(r[c.key], c.kind))),
        columns: cols.map((c) => ({
          title: c.label, type: "text", readOnly: true, width: widthFor(c), align: numeric(c.kind) ? "right" : "left",
          render: (cell: HTMLTableCellElement, value: unknown) => {
            cell.textContent = shown(value, c.kind);
            if (c.key === "due" && Number(value) > 0) cell.classList.add("is-due");
          },
        })),
        footers: foot ? [cols.map((c, i) => (i === 0 ? String(foot[c.key] ?? "Total") : shown(foot[c.key], c.kind)))] : undefined,
        editable: false, allowInsertRow: false, allowInsertColumn: false, allowDeleteRow: false, allowDeleteColumn: false,
        allowRenameColumn: false, columnDrag: false, rowDrag: false, columnResize: true, columnSorting: true, filters: true,
        selectionCopy: true, wordWrap: false, freezeColumns: 1,
        tableOverflow: true, tableHeight: height, tableWidth: "100%",
        minDimensions: [cols.length, Math.max(data.length, 1)],
      }],
    } as never);
    const sheet = sheets[0];
    const open = (e: Event) => {
      if (!onopen) return;
      const td = (e.target as HTMLElement).closest("td[data-y]");
      const y = td ? Number(td.getAttribute("data-y")) : NaN;
      if (Number.isFinite(y) && data[y]) onopen(data[y]);
    };
    host.addEventListener("dblclick", open);
    return () => {
      host.removeEventListener("dblclick", open);
      try { jspreadsheet.destroy(host as never, true); } catch { /* already gone */ }
      host.innerHTML = "";
      void sheet;
    };
  });
</script>

<div class="sheet" role="region" aria-label="{label}: spreadsheet. Click a heading to sort; use the filter row to narrow; select cells and press Ctrl+C to copy.">
  <div bind:this={host}></div>
</div>

<style>
  /* Excel-like look in the app's colours; works in light and dark. */
  .sheet { --sheet-grid: var(--border); --sheet-head: var(--muted); min-width: 0; }
  .sheet :global(.jss_container), .sheet :global(.jexcel_container) { width: 100%; padding: 0; }
  .sheet :global(.jss_content), .sheet :global(.jexcel_content) { width: 100%; box-shadow: none; border: 1px solid var(--sheet-grid); border-radius: 8px; padding: 0; }
  .sheet :global(table.jss_worksheet), .sheet :global(table.jexcel) { font: 400 13px/1.4 var(--font-sans); color: var(--foreground); background: var(--card); border-color: var(--sheet-grid); }
  .sheet :global(.jss_worksheet > thead > tr > td), .sheet :global(.jexcel > thead > tr > td) {
    background-color: var(--sheet-head); color: var(--muted-foreground); font-weight: 600; border-color: var(--sheet-grid); padding: 6px 8px; }
  .sheet :global(.jss_worksheet > tbody > tr > td), .sheet :global(.jexcel > tbody > tr > td) { border-color: var(--sheet-grid); padding: 5px 8px; white-space: nowrap; font-variant-numeric: tabular-nums; }
  .sheet :global(.jss_worksheet > tbody > tr > td:first-child), .sheet :global(.jexcel > tbody > tr > td:first-child) { background-color: var(--sheet-head); color: var(--muted-foreground); }
  .sheet :global(.jss_worksheet > tbody > tr:hover > td:not(:first-child)) { background: color-mix(in srgb, var(--primary) 5%, var(--card)); }
  /* read-only cells are greyed by default; ours are all read-only, so show them at full strength */
  .sheet :global(.jss_worksheet > tbody > tr > td.readonly) { color: var(--foreground); }
  .sheet :global(.jss_worksheet > tbody > tr > td.readonly.is-due) { color: var(--destructive); font-weight: 600; }
  .sheet :global(.jss_worksheet > tfoot > tr > td), .sheet :global(.jexcel > tfoot > tr > td) {
    background-color: var(--sheet-head); font-weight: 700; color: var(--foreground); border-color: var(--sheet-grid); border-top: 2px solid var(--input); padding: 6px 8px; }
  .sheet :global(.jss_filter), .sheet :global(.jexcel_filter) { background: var(--card); }
  .sheet :global(.jss_filter input), .sheet :global(.jexcel_filter input) { height: 26px; border: 1px solid var(--input); border-radius: 5px; background: var(--background); color: var(--foreground); }
  .sheet :global(.jss_worksheet .highlight), .sheet :global(.jexcel .highlight) { background-color: color-mix(in srgb, var(--primary) 10%, transparent); }
  .sheet :global(.jss_corner), .sheet :global(.jexcel_corner) { background: var(--primary); border-color: var(--card); }
  @media print {
    .sheet :global(.jss_content), .sheet :global(.jexcel_content) { max-height: none !important; height: auto !important; overflow: visible !important; }
    .sheet :global(.jss_filter), .sheet :global(.jexcel_filter) { display: none; }
  }
</style>
