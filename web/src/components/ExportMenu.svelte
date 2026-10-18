<script lang="ts">
  import Icon from "./Icon.svelte";
  import { toasts, notify, notifyError } from "../lib/toast.svelte";
  import { tooltip } from "../lib/tooltip";

  // "Export" with a small menu: PDF or Excel. The file is fetched with the session cookie (a GET, so no CSRF
  // token), then handed to the browser as a download, so a refusal or a server error shows as a toast.
  //   kind "bills":  /api/exports/bills.xlsx?…   (the bills list's own query string)
  //   kind "report": /api/reports/dues?…&format=xlsx
  type Query = Record<string, string | number | boolean | null | undefined>;
  let { path, query = {}, kind = "report", label = "Export", disabled = false, workbook }: {
    path: string; query?: Query; kind?: "bills" | "report"; label?: string; disabled?: boolean;
    /** Also offer one Excel file with every sheet (e.g. /api/reports/workbook.xlsx with the same dates). */
    workbook?: { path: string; query?: Query; about?: string; label?: string };
  } = $props();

  // The server includes at most this many rows in a file (it says so in the file's subtitle when it stops).
  const MAX_ROWS = "20,000";
  const FORMATS = [
    { id: "pdf" as const, label: "PDF", icon: "fileText",
      about: `Printable A4 pages with the centre's name, page numbers and totals. Up to ${MAX_ROWS} rows; long lists are easier in Excel.` },
    { id: "xlsx" as const, label: "Excel (.xlsx)", icon: "sheet",
      about: `A spreadsheet with real numbers you can sort, filter and add up. Up to ${MAX_ROWS} rows; narrow the filters for more.` },
  ];

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
  function url(format: "pdf" | "xlsx" | "book"): string {
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

  async function download(format: "pdf" | "xlsx" | "book") {
    open = false;
    if (busy) return;
    busy = true;
    const what = format === "pdf" ? "PDF" : format === "book" ? "workbook" : "Excel file";
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

<style>
  .export { position: relative; display: inline-block; }
  .export-menu { position: absolute; right: 0; top: calc(100% + 4px); z-index: 200; width: 280px; padding: 5px; background: var(--popover);
    border: 1px solid var(--border); border-radius: 10px; box-shadow: var(--shadow-lg); }
  .export-item { display: flex; align-items: flex-start; gap: 10px; width: 100%; padding: 8px 10px; border: 0; border-radius: 7px;
    background: none; color: var(--foreground); font: 500 13.5px var(--font-sans); cursor: pointer; text-align: left; }
  .export-item:hover, .export-item:focus-visible { background: var(--muted); }
  .export-item :global(.icon) { color: var(--muted-foreground); margin-top: 2px; flex: none; }
  .export-label { display: block; }
  .export-sep { height: 1px; margin: 4px 6px; background: var(--border); }
  .export-about { display: block; margin-top: 2px; font-size: 12px; font-weight: 400; line-height: 1.4; color: var(--muted-foreground); }
</style>
