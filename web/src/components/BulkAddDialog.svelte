<script lang="ts">
  import { api, ApiError, post } from "../lib/api";
  import { notify, notifyError } from "../lib/toast.svelte";
  import type { Department, TestType } from "../lib/types";
  import { ResumableUpload } from "../lib/upload.svelte";
  import Button from "./Button.svelte";
  import Dialog from "./Dialog.svelte";
  import Icon from "./Icon.svelte";
  import UploadProgress from "./UploadProgress.svelte";

  // Add many departments, test types or tests at once: type them in the grid, paste from a spreadsheet, or upload an
  // Excel sheet (sent in pieces, with pause and resume). Nothing is added until every row is right; each row's
  // problem shows under it.
  type Kind = "departments" | "test-types" | "tests" | "doctors";
  let { open = $bindable(false), kind, departments = [], types = [], onadded }: {
    open?: boolean; kind: Kind; departments?: Department[]; types?: TestType[]; onadded: () => void;
  } = $props();

  type Col = { key: string; label: string; placeholder?: string; list?: string; yesNo?: boolean; width?: string; money?: boolean };
  const COLUMNS: Record<Kind, Col[]> = {
    "departments": [{ key: "name", label: "Department", placeholder: "e.g. Pathology" }],
    "test-types": [{ key: "name", label: "Test type", placeholder: "e.g. CT scan" }, { key: "imaging", label: "Has images", yesNo: true, width: "130px" }],
    "tests": [{ key: "name", label: "Test name", placeholder: "e.g. CBC" }, { key: "code", label: "Short code", width: "110px" },
              { key: "department", label: "Department", list: "departments" }, { key: "test_type", label: "Test type", list: "types" },
              { key: "price", label: "Price (₹)", width: "110px", money: true }],
    "doctors": [{ key: "name", label: "Doctor or hospital", placeholder: "e.g. Dr. Kakali Sarkar" },
                { key: "qualification", label: "Qualification", placeholder: "e.g. MBBS, MD" },
                { key: "phone", label: "Phone", placeholder: "98765 43210", width: "160px" }],
  };
  const NAMES: Record<Kind, [string, string]> = { "departments": ["department", "departments"], "test-types": ["test type", "test types"], "tests": ["test", "tests"],
                                           "doctors": ["doctor or hospital", "doctors and hospitals"] };
  const cols = $derived(COLUMNS[kind]);
  const uid = $props.id();

  type Row = { values: Record<string, string>; errors: Record<string, string> };
  const blank = (): Row => ({ values: Object.fromEntries(COLUMNS[kind].map((c) => [c.key, c.yesNo ? "No" : ""])), errors: {} });
  const filled = (r: Row) => cols.some((c) => !c.yesNo && r.values[c.key]?.trim());

  let rows = $state<Row[]>([]);
  let saving = $state(false);
  let upload = $state<ResumableUpload | null>(null);
  let uploadName = $state("");
  let reading = $state(false);
  let fileInput: HTMLInputElement;

  const count = $derived(rows.filter(filled).length);
  const problems = $derived(rows.filter((r) => filled(r) && Object.keys(r.errors).length).length);

  $effect(() => {
    if (open) { rows = [blank(), blank(), blank()]; upload = null; }
  });

  function addRow() { rows.push(blank()); }
  function removeRow(i: number) { rows.splice(i, 1); if (!rows.length) rows.push(blank()); }
  function edited(r: Row, key: string) { delete r.errors[key]; }

  // Pasting cells copied from Excel fills the grid from that cell rightwards and downwards.
  function paste(e: ClipboardEvent, rowAt: number, colAt: number) {
    const text = e.clipboardData?.getData("text/plain") ?? "";
    if (!text.includes("\t") && !text.includes("\n")) return;
    e.preventDefault();
    const lines = text.replace(/\r/g, "").split("\n").filter((l, i, all) => l.trim() || i < all.length - 1);
    lines.forEach((line, i) => {
      while (rows.length <= rowAt + i) rows.push(blank());
      line.split("\t").forEach((cell, j) => {
        const col = cols[colAt + j];
        if (col) { rows[rowAt + i].values[col.key] = cell.trim(); delete rows[rowAt + i].errors[col.key]; }
      });
    });
  }

  // ---------- Excel upload ----------
  async function chosen(e: Event) {
    const file = (e.currentTarget as HTMLInputElement).files?.[0];
    (e.currentTarget as HTMLInputElement).value = "";
    if (!file) return;
    upload = new ResumableUpload(file, "catalogue");
    uploadName = file.name;
    await send();
  }

  async function send() {
    if (!upload) return;
    try {
      const id = await upload.start();
      reading = true;
      const res = await post<{ rows: Row[] }>(`/api/catalogue/${kind}/import`, { upload_id: id });
      rows = [...rows.filter(filled), ...res.rows];
      const bad = res.rows.filter((r) => Object.keys(r.errors).length).length;
      notify(`${res.rows.length} row${res.rows.length === 1 ? "" : "s"} read from ${uploadName}.${bad ? ` ${bad} need fixing.` : " Check them, then add."}`,
             { title: "Sheet read" });
      upload = null;
    } catch (e) {
      if ((e as Error).name === "AbortError") return; // paused
      if (upload && upload.status === "done") upload = null;
      if (!(upload?.status === "error")) notifyError(e, { title: "Couldn't read the sheet" });
    } finally {
      reading = false;
    }
  }

  async function cancelUpload() {
    await upload?.cancel();
    upload = null;
  }

  async function template() {
    try {
      const res = await fetch(`/api/catalogue/${kind}/template`, { credentials: "same-origin" });
      if (!res.ok) throw new Error((await res.json().catch(() => null))?.message ?? `Couldn't get the template (${res.status}).`);
      const href = URL.createObjectURL(await res.blob());
      const a = Object.assign(document.createElement("a"), { href, download: `${kind}-template.xlsx` });
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(href), 30_000);
    } catch (e) {
      notifyError(e, { title: "Couldn't download the template" });
    }
  }

  // ---------- save ----------
  async function save() {
    const sending = rows.map((r, i) => ({ r, i })).filter(({ r }) => filled(r));
    if (!sending.length) { notify("Fill in at least one row.", { kind: "error" }); return; }
    for (const { r } of sending) r.errors = {};
    saving = true;
    try {
      const res = await api<{ added: number }>("POST", `/api/catalogue/${kind}/bulk`,
                                               { body: { rows: sending.map(({ r }) => r.values) }, progress: `Adding ${sending.length} ${NAMES[kind][1]}…` });
      notify(`${res.added} ${res.added === 1 ? NAMES[kind][0] : NAMES[kind][1]} added.`);
      open = false;
      onadded();
    } catch (e) {
      if (e instanceof ApiError && e.detail.some((d) => d.field.startsWith("rows."))) {
        for (const d of e.detail) {
          const [, at, field] = d.field.split(".");
          const target = sending[Number(at)]?.r;
          if (target && field) target.errors[field] = d.message;
        }
        notify(e.message, { kind: "error", title: "Nothing added yet" });
      } else notifyError(e, { title: "Couldn't add them" });
    } finally {
      saving = false;
    }
  }
</script>

<Dialog bind:open title="Add {NAMES[kind][1]}" icon="sheet" tone="info" wide
        description="Type them below, paste rows copied from Excel, or upload an Excel sheet. Nothing is added until every row is right.">
  <div class="stack">
    <div class="row gap-sm wrap">
      <input bind:this={fileInput} type="file" accept=".xlsx,.csv" class="sr-only" id="{uid}-file" onchange={chosen} />
      <Button icon="upload" disabled={!!upload || reading} loading={reading} loadingText="Reading the sheet…" onclick={() => fileInput.click()}>Upload Excel sheet</Button>
      <Button variant="ghost" icon="download" onclick={template}>Download template</Button>
      <span class="text-sm text-muted">.xlsx or .csv, up to 10 MB and {1000} rows. The first sheet is read.</span>
    </div>

    {#if upload}
      <UploadProgress {upload} filename={uploadName} onresume={send} oncancel={cancelUpload} />
    {/if}

    {#if kind === "tests"}
      <datalist id="{uid}-departments">{#each departments.filter((d) => d.is_active) as d (d.id)}<option value={d.name}></option>{/each}</datalist>
      <datalist id="{uid}-types">{#each types.filter((t) => t.is_active) as t (t.id)}<option value={t.name}></option>{/each}</datalist>
    {/if}

    <div class="table-wrap bulk">
      <table class="table">
        <thead>
          <tr><th class="num" style="width: 40px">#</th>
            {#each cols as c (c.key)}<th style:width={c.width}>{c.label}</th>{/each}
            <th style="width: 44px"><span class="sr-only">Remove</span></th></tr>
        </thead>
        <tbody>
          {#each rows as r, i (r)}
            <tr class:has-error={Object.keys(r.errors).length}>
              <td class="num text-muted">{i + 1}</td>
              {#each cols as c, j (c.key)}
                <td>
                  {#if c.yesNo}
                    <select class="select select-sm" aria-label="{c.label}, row {i + 1}" bind:value={r.values[c.key]} onchange={() => edited(r, c.key)}
                            aria-invalid={!!r.errors[c.key]}>
                      <option>No</option><option>Yes</option>
                    </select>
                  {:else}
                    <input class="input input-sm" class:money={c.money} aria-label="{c.label}, row {i + 1}" placeholder={i === 0 ? c.placeholder ?? "" : ""}
                           list={c.list ? `${uid}-${c.list}` : undefined} inputmode={c.money ? "decimal" : undefined}
                           bind:value={r.values[c.key]} oninput={() => edited(r, c.key)} onpaste={(e) => paste(e, i, j)}
                           aria-invalid={!!r.errors[c.key]} />
                  {/if}
                  {#if r.errors[c.key]}<div class="cell-error"><Icon name="alert" size="sm" /> {r.errors[c.key]}</div>{/if}
                </td>
              {/each}
              <td><Button size="sm" variant="ghost" icon="x" aria-label="Remove row {i + 1}" tooltip="Remove this row" onclick={() => removeRow(i)} /></td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <div class="row gap-sm">
      <Button size="sm" variant="ghost" icon="plus" onclick={addRow}>Add a row</Button>
      {#if problems}<span class="text-sm cell-error"><Icon name="alert" size="sm" /> {problems} row{problems === 1 ? "" : "s"} to fix</span>{/if}
    </div>
  </div>
  {#snippet footer()}
    <Button onclick={() => (open = false)}>Cancel</Button>
    <Button variant="primary" icon="plus" disabled={!count || !!upload} loading={saving} loadingText="Adding…" onclick={save}>
      Add {count || ""} {count === 1 ? NAMES[kind][0] : NAMES[kind][1]}
    </Button>
  {/snippet}
</Dialog>

<style>
  .bulk { max-height: 50vh; overflow: auto; }
  .bulk td { vertical-align: top; padding-top: 6px; padding-bottom: 6px; }
  .bulk .input, .bulk .select { width: 100%; min-width: 90px; }
  .cell-error { color: var(--destructive); font-size: 0.8125rem; margin-top: 4px; display: flex; gap: 4px; align-items: flex-start; }
  .wrap { flex-wrap: wrap; align-items: center; }
</style>
