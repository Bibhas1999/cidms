<script lang="ts">
  import Icon from "./Icon.svelte";
  import { toasts, notify, notifyError } from "../lib/toast.svelte";
  import { tooltip } from "../lib/tooltip";

  // "Export" with a small menu: PDF, Excel, and (bills lists only) CSV and Word. The file is fetched with the
  // session cookie (a GET, so no CSRF token), then handed to the browser as a download, so a refusal or a
  // server error shows as a toast.
  //   kind "bills":  /api/exports/bills.xlsx?…   (the bills list's own query string)
  //   kind "report": /api/reports/dues?…&format=xlsx
  type Format = "pdf" | "xlsx" | "csv" | "docx";
  type Query = Record<string, string | number | boolean | null | undefined>;
  let { path, query = {}, kind = "report", label = "Export", disabled = false, workbook }: {
    path: string; query?: Query; kind?: "bills" | "report"; label?: string; disabled?: boolean;
    /** Also offer one Excel file with every sheet (e.g. /api/reports/workbook.xlsx with the same dates). */
    workbook?: { path: string; query?: Query; about?: string; label?: string };
  } = $props();

  // The server includes at most this many rows in a file (it says so in the file's subtitle when it stops).
  const MAX_ROWS = "20,000";
  const ALL_FORMATS: { id: Format; label: string; icon: string; about: string }[] = [
    { id: "pdf", label: "PDF", icon: "fileText",
      about: `Printable A4 pages with the centre's name, page numbers and totals. Up to ${MAX_ROWS} rows; long lists are easier in Excel.` },
    { id: "xlsx", label: "Excel (.xlsx)", icon: "sheet",
      about: `A spreadsheet with real numbers you can sort, filter and add up. Up to ${MAX_ROWS} rows; narrow the filters for more.` },
    { id: "csv", label: "CSV", icon: "fileText",
      about: `Plain comma-separated text, for importing into other software. Up to ${MAX_ROWS} rows.` },
    { id: "docx", label: "Word (.docx)", icon: "fileText",
      about: `A formatted document you can edit or add to a letter. Up to ${MAX_ROWS} rows.` },
  ];
  // CSV and Word are only offered for a bills-style list (not yet wired up for every report).
  const FORMATS = $derived(kind === "bills" ? ALL_FORMATS : ALL_FORMATS.filter((f) => f.id === "pdf" || f.id === "xlsx"));

  const uid = $props.id();
  let open = $state(false);
  let busy = $state(false);
  let wrap = $state<HTMLElement>();
  let button = $state<HTMLButtonElement>();

  const qs = (q: Query) => {
    const out = new URLSearchParams();
    for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== null && v !== "" && v !== false) out.set(k, String(v));
    return out;
  };
  function url(format: Format | "book"): string {
    if (format === "book" && workbook) { const s = qs(workbook.query ?? {}).toString(); return `${workbook.path}${s ? `?${s}` : ""}`; }
    const q = qs(query);
    if (kind === "report") q.set("format", format);
    const s = q.toString();
    return `${kind === "bills" ? `${path}.${format}` : path}${s ? `?${s}` : ""}`;
  }

  function fileName(header: string | null, fallback: string): string {
    const m = header?.match(/filename="?([^";]+)"?/i);
    return m ? m[1] : fallback;
  }

  const WHAT: Record<Format, string> = { pdf: "PDF", xlsx: "Excel file", csv: "CSV file", docx: "Word document" };

  async function download(format: Format | "book") {
    open = false;
    if (busy) return;
    busy = true;
    const what = format === "book" ? "workbook" : WHAT[format];
    const progress = notify(`Preparing the ${what}…`, { kind: "progress" });
    try {
      const res = await fetch(url(format), { credentials: "same-origin" });
      if (!res.ok) {
        let message = `Couldn't prepare the ${what} (${res.status}).`;
        try { message = (await res.json()).message ?? message; } catch { /* not JSON */ }
        throw new Error(message);
      }
      const blob = await res.blob();
      const href = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = href;
      a.download = fileName(res.headers.get("Content-Disposition"), `export.${format === "book" ? "xlsx" : format}`);
      a.style.display = "none";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(href), 30_000);
    } catch (e) {
      notifyError(e, { title: "Export failed" });
    } finally {
      if (progress !== null) toasts.dismiss(progress);
      busy = false;
    }
  }

  $effect(() => {
    if (!open) return;
    const close = (e: Event) => { if (!wrap?.contains(e.target as Node)) open = false; };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") { open = false; button?.focus(); }
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const items = [...(wrap?.querySelectorAll<HTMLElement>("[role=menuitem]") ?? [])];
        const i = items.indexOf(document.activeElement as HTMLElement);
        items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length]?.focus();
      }
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", key); };
  });

  function toggle() {
    open = !open;
    if (open) queueMicrotask(() => (wrap?.querySelector("[role=menuitem]") as HTMLElement | null)?.focus());
  }
</script>

<div class="export" bind:this={wrap}>
  <button bind:this={button} type="button" class="btn btn-outline" aria-haspopup="menu" aria-expanded={open}
          use:tooltip={{ text: "Download what's on screen, with the same filters", placement: "bottom" }}
          disabled={disabled || busy} onclick={toggle}>
    <Icon name="download" /> {busy ? "Preparing…" : label} <Icon name="chevronDown" size="sm" />
  </button>
  {#if open}
    <div class="export-menu" role="menu">
      {#each FORMATS as f (f.id)}
        <button role="menuitem" type="button" class="export-item" aria-describedby="{uid}-{f.id}" onclick={() => download(f.id)}>
          <Icon name={f.icon} size="sm" />
          <span><span class="export-label">{f.label}</span><span class="export-about" id="{uid}-{f.id}">{f.about}</span></span>
        </button>
      {/each}
      {#if workbook}
        <div class="export-sep" role="separator"></div>
        <button role="menuitem" type="button" class="export-item" aria-describedby="{uid}-book" onclick={() => download("book")}>
          <Icon name="layers" size="sm" />
          <span><span class="export-label">{workbook.label ?? "Whole workbook (.xlsx)"}</span>
            <span class="export-about" id="{uid}-book">{workbook.about ?? "One Excel file with every sheet, each on its own tab, for the same dates."}</span></span>
        </button>
      {/if}
    </div>
  {/if}
</div>

<style src="./styles/ExportMenu.css"></style>
