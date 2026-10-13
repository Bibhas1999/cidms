<script lang="ts">
  import Dialog from "./Dialog.svelte";
  import Field from "./Field.svelte";
  import Icon from "./Icon.svelte";
  import InfoTip from "./InfoTip.svelte";
  import RowMenu, { type RowAction } from "./RowMenu.svelte";
  import { get, post, put } from "../lib/api";
  import { count, dateTime } from "../lib/format";
  import { notify, notifyError } from "../lib/toast.svelte";

  // One centre's own backups: its schedule, "Back up now", and the copies, each downloadable as an Excel workbook,
  // as SQL or as the backup file, and restorable. Used by the owner (Settings > Backups, base "/api/backups") and
  // by the platform for any client (base "/api/platform/clients/<id>/backups", without the schedule).
  let { base, schedule = true, who = "your centre" }: { base: string; schedule?: boolean; who?: string } = $props();

  interface Option { days: number; label: string }
  interface Run {
    id: string; trigger: "scheduled" | "manual" | "restore"; status: "running" | "ok" | "failed"; started_at: string;
    finished_at: string | null; requested_by_name: string; file: string; size_bytes: number; counts: Record<string, number>;
    message: string; available: boolean; restorable: boolean;
  }
  interface Overview {
    settings: { enabled: boolean; every_days: number; at_time: string; keep_days: number; next_run_at: string | null };
    cycles: Option[]; keep_options: Option[]; runs: Run[]; busy: boolean;
  }

  let data = $state<Overview | null>(null);
  let values = $state({ enabled: true, every_days: 1, at_time: "23:30", keep_days: 30 });
  let saved = $state("");
  let saving = $state(false);
  let asking = $state(false);

  function load(o: Overview) {
    data = o;
    values = { enabled: o.settings.enabled, every_days: o.settings.every_days, at_time: o.settings.at_time, keep_days: o.settings.keep_days };
    saved = JSON.stringify(values);
  }
  const refresh = () => get<Overview>(base).then(load);

  $effect(() => {
    refresh().catch((e) => notifyError(e, { title: "Couldn't load the backups" }));
    // While a copy or restore is running, look again every 5 seconds so the result shows up by itself.
    const timer = setInterval(() => { if (data?.busy) refresh().catch(() => {}); }, 5_000);
    return () => clearInterval(timer);
  });

  const dirty = $derived(!!data && JSON.stringify(values) !== saved);

  async function save(e: Event) {
    e.preventDefault();
    saving = true;
    try {
      load(await put<Overview>(base, values));
      notify(values.enabled ? "The backup schedule is saved." : "Scheduled backups are off. You can still back up now.");
    } catch (err) {
      notifyError(err, { title: "Couldn't save the backup schedule" });
    } finally {
      saving = false;
    }
  }

  async function backUpNow() {
    asking = true;
    try {
      load(await post<Overview>(`${base}/run`));
      notify("Backing up now. It shows in the list in a few seconds.", { kind: "info" });
    } catch (err) {
      notifyError(err, { title: "Couldn't start a backup" });
    } finally {
      asking = false;
    }
  }

  // ---------- restore ----------
  let restoring = $state<Run | null>(null);
  let restoreOpen = $state(false);
  let typed = $state("");
  let sending = $state(false);

  async function askRestore(e: Event) {
    e.preventDefault();
    if (!restoring || typed.trim() !== "RESTORE") return;
    sending = true;
    try {
      load(await post<Overview>(`${base}/${restoring.id}/restore`, { confirm: typed.trim() }));
      restoreOpen = false;
      notify(`Restoring now. A fresh copy is made first, then ${who === "your centre" ? "everyone at the centre signs in again" : "everyone there signs in again"}.`,
             { kind: "info", title: "Restore started" });
    } catch (err) {
      notifyError(err, { title: "Couldn't start the restore" });
    } finally {
      sending = false;
    }
  }

  function actionsFor(r: Run): RowAction[] {
    if (r.trigger === "restore" || r.status !== "ok") return [];
    const gone = "This copy isn't kept any more.";
    const link = (format: string) => `${base}/${r.id}/download?format=${format}`;
    return [
      { label: "Download Excel", icon: "download", href: link("xlsx"), disabled: !r.available, hint: r.available ? "A sheet for patients, bills, payments, tests…" : gone },
      { label: "Download SQL", icon: "download", href: link("sql"), disabled: !r.available, hint: r.available ? "The records as SQL INSERT statements" : gone },
      { label: "Download backup file", icon: "download", href: link("copy"), disabled: !r.available, hint: r.available ? "The copy itself, as CIDMS restores it" : gone },
      { label: "Restore…", icon: "refresh", tone: "danger", disabled: !r.restorable || !!data?.busy,
        hint: !r.available ? gone : !r.restorable ? "Made by an earlier version of CIDMS: download only" : data?.busy ? "A backup or restore is running" : "Put every record back to this copy",
        onclick: () => { restoring = r; typed = ""; restoreOpen = true; } },
    ];
  }

  const size = (b: number) => (b >= 1_048_576 ? `${(b / 1_048_576).toFixed(1)} MB` : b >= 1024 ? `${Math.round(b / 1024)} KB` : b ? `${b} B` : "—");
  const what = (r: Run) => (r.counts?.invoices !== undefined ? `${count(r.counts.invoices)} bills · ${count(r.counts.patients ?? 0)} patients` : "");
  const why = (r: Run) => (r.trigger === "restore" ? "Restore" : r.trigger === "manual" ? (r.message.startsWith("The data just before") ? "Before a restore" : "Asked for") : "Scheduled");
  const cycleLabel = $derived(data?.cycles.find((c) => c.days === values.every_days)?.label.toLowerCase() ?? "");
  const lastOk = $derived(data?.runs.find((r) => r.status === "ok" && r.trigger !== "restore"));
</script>

<form class="card" onsubmit={save} novalidate>
  <div class="card-header"><div><h2 class="card-title">Backups</h2>
    <p class="card-description">A copy of {who === "your centre" ? "your centre's" : `${who}'s`} records: patients, bills, payments, reports, tests, doctors and settings. Times are India time.
      <InfoTip about="what a backup holds" text="Staff accounts, roles and API keys aren't in it, so restoring never changes who can sign in. Scanned images stay in the image store and aren't part of it." /></p></div></div>
  <div class="card-content stack-lg">
    <div class="status" aria-live="polite">
      <div><span class="label">Next backup</span>
        <span class="font-semibold">{!data ? "…" : !data.settings.enabled ? "Scheduled backups are off" : data.settings.next_run_at ? dateTime(data.settings.next_run_at) : "—"}</span></div>
      <div><span class="label">Last good backup</span>
        <span class="font-semibold">{!data ? "…" : lastOk ? `${dateTime(lastOk.finished_at ?? lastOk.started_at)} · ${size(lastOk.size_bytes)}` : "None yet"}</span></div>
    </div>

    {#if schedule}
      <label class="check-row">
        <input type="checkbox" class="checkbox" bind:checked={values.enabled} />
        <span><span class="font-semibold">Back up automatically</span>
          <span class="text-sm text-muted">· when this is off, only "Back up now" makes a copy.</span></span>
      </label>
      <div class="grid-3 fields">
        <Field id="cb_every" label="How often">
          {#snippet children({ describedby })}
            <select id="cb_every" class="select" bind:value={values.every_days} disabled={!values.enabled} aria-describedby={describedby}>
              {#each data?.cycles ?? [] as c (c.days)}<option value={c.days}>{c.label}</option>{/each}
            </select>
          {/snippet}
        </Field>
        <Field id="cb_time" label="At" tip="Late evening is best: billing is quiet and the day's bills are in.">
          {#snippet children({ describedby })}
            <input id="cb_time" class="input" type="time" step="300" bind:value={values.at_time} disabled={!values.enabled} aria-describedby={describedby} required />
          {/snippet}
        </Field>
        <Field id="cb_keep" label="Keep copies for" tip="Older copies are deleted after each backup. Forever: none are deleted.">
          {#snippet children({ describedby })}
            <select id="cb_keep" class="select" bind:value={values.keep_days} aria-describedby={describedby}>
              {#each data?.keep_options ?? [] as k (k.days)}<option value={k.days}>{k.label}</option>{/each}
            </select>
          {/snippet}
        </Field>
      </div>
      {#if values.enabled && data}
        <p class="text-sm text-muted">Backed up {cycleLabel} at {values.at_time}, {values.keep_days === 0 ? "and every copy kept" : `and each copy kept for ${data.keep_options.find((k) => k.days === values.keep_days)?.label}`}.</p>
      {/if}
    {/if}
  </div>
  <div class="card-footer actions">
    <button type="button" class="btn btn-outline" onclick={backUpNow} disabled={!data || asking || data.busy}>
      <Icon name="download" size="sm" />{data?.busy ? "Working…" : "Back up now"}
    </button>
    {#if schedule}<button type="submit" class="btn btn-primary" disabled={!dirty || saving}>{saving ? "Saving…" : "Save schedule"}</button>{/if}
  </div>
</form>

<section class="card" aria-labelledby="cb-runs">
  <div class="card-header"><div><h2 class="card-title" id="cb-runs">Copies</h2>
    <p class="card-description">The last 30, newest first. Download or restore one from its ⋮ menu.</p></div></div>
  <div class="table-wrap">
    <table class="table" style="min-width: 0">
      <thead><tr><th>When</th><th class="hide-sm">Why</th><th>Result</th><th class="hide-sm">Holds</th><th class="num">Size</th><th><span class="sr-only">Actions</span></th></tr></thead>
      <tbody>
        {#each data?.runs ?? [] as r (r.id)}
          <tr>
            <td class="tabular">{dateTime(r.finished_at ?? r.started_at)}{#if r.requested_by_name}<div class="cell-sub">{r.requested_by_name}</div>{/if}</td>
            <td class="hide-sm text-sm">{why(r)}</td>
            <td>
              {#if r.status === "ok"}<span class="badge badge-success"><Icon name="check" size="sm" />{r.trigger === "restore" ? "Restored" : "Done"}</span>{#if r.trigger !== "restore" && !r.available}<span class="text-sm text-muted"> · deleted</span>{/if}
              {:else if r.status === "running"}<span class="badge badge-info"><Icon name="clock" size="sm" />{r.trigger === "restore" ? "Restoring" : "Running"}</span>
              {:else}<span class="badge badge-destructive"><Icon name="alert" size="sm" />Failed</span>{/if}
              {#if r.message && r.trigger !== "scheduled"}<div class="cell-sub">{r.message}</div>{/if}
            </td>
            <td class="hide-sm text-sm">{r.trigger === "restore" ? "" : what(r)}</td>
            <td class="num tabular">{r.trigger === "restore" ? "" : size(r.size_bytes)}</td>
            <td class="num">{#if actionsFor(r).length}<RowMenu actions={actionsFor(r)} label="Actions for the copy of {dateTime(r.started_at)}" />{/if}</td>
          </tr>
        {:else}
          <tr><td colspan="6"><div class="empty"><Icon name="inbox" />{data ? "No copies yet. Back up now to make the first." : "Loading…"}</div></td></tr>
        {/each}
      </tbody>
    </table>
  </div>
</section>

<Dialog bind:open={restoreOpen} title="Restore this copy?" icon="alert" tone="destructive"
        description={restoring ? `Back to ${dateTime(restoring.started_at)}${what(restoring) ? ` (${what(restoring)})` : ""}` : ""}>
  <form id="cb-restore-form" class="stack" onsubmit={askRestore} novalidate>
    <ul class="restore-list text-sm">
      <li>Every record of {who} goes back to this moment: bills, payments, patients, reports, tests, doctors and settings made or changed since are gone.</li>
      <li>A fresh copy of the records as they are now is made first, so this can be undone by restoring that copy.</li>
      <li>Staff accounts and roles stay as they are. Everyone signs in again afterwards.</li>
    </ul>
    <Field id="cb-restore-confirm" label="Type RESTORE to confirm" required>
      {#snippet children({ describedby })}
        <input id="cb-restore-confirm" class="input mono" autocomplete="off" spellcheck="false" bind:value={typed} aria-describedby={describedby} />
      {/snippet}
    </Field>
  </form>
  {#snippet footer()}
    <button type="button" class="btn btn-outline" onclick={() => (restoreOpen = false)}>Cancel</button>
    <button type="submit" form="cb-restore-form" class="btn btn-destructive" disabled={sending || typed.trim() !== "RESTORE"}>{sending ? "Starting…" : "Restore"}</button>
  {/snippet}
</Dialog>

<style>
  .status { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; padding: 12px 14px; border-radius: 10px; background: var(--muted); }
  .status > div { display: flex; flex-direction: column; gap: 2px; }
  .fields { align-items: start; }
  .actions { display: flex; justify-content: flex-end; gap: 10px; flex-wrap: wrap; }
  .restore-list { margin: 0; padding-left: 18px; display: grid; gap: 6px; }
  @media (max-width: 760px) { .hide-sm { display: none; } .fields { grid-template-columns: 1fr !important; } .status { grid-template-columns: 1fr; } }
</style>
