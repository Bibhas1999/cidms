<script lang="ts">
  import Field from "../../components/Field.svelte";
  import Icon from "../../components/Icon.svelte";
  import InfoTip from "../../components/InfoTip.svelte";
  import { get, post, put } from "../../lib/api";
  import { dateTime } from "../../lib/format";
  import { notify, notifyError } from "../../lib/toast.svelte";

  // When the whole database is copied (all centres): the time of day, how often, and how long copies are kept,
  // plus "Back up now". The server checks every 5 minutes whether one is due, so a backup starts within 5
  // minutes of its time. Platform owner only.
  let {}: { embedded?: boolean } = $props();

  interface Option { days: number; label: string }
  interface Settings { enabled: boolean; every_days: number; at_time: string; keep_days: number; next_run_at: string | null; requested_at: string | null }
  interface Run {
    id: string; trigger: "scheduled" | "manual"; scheduled_for: string | null; started_at: string; finished_at: string | null;
    status: "running" | "ok" | "failed"; file: string; size_bytes: number; message: string; kept: boolean;
  }
  interface Overview { settings: Settings; cycles: Option[]; keep_options: Option[]; timezone: string; runs: Run[] }

  let data = $state<Overview | null>(null);
  let values = $state({ enabled: true, every_days: 1, at_time: "23:00", keep_days: 30 });
  let saved = $state("");
  let saving = $state(false);
  let asking = $state(false);

  function load(o: Overview) {
    data = o;
    values = { enabled: o.settings.enabled, every_days: o.settings.every_days, at_time: o.settings.at_time, keep_days: o.settings.keep_days };
    saved = JSON.stringify(values);
  }
  const refresh = () => get<Overview>("/api/platform/backups").then(load);

  $effect(() => {
    refresh().catch((e) => notifyError(e, { title: "Couldn't load the backup settings" }));
    // While a backup is asked for or running, look again every 20 seconds so its result shows up by itself.
    const timer = setInterval(() => { if (data?.settings.requested_at || data?.runs.some((r) => r.status === "running")) refresh().catch(() => {}); }, 20_000);
    return () => clearInterval(timer);
  });

  const dirty = $derived(!!data && JSON.stringify(values) !== saved);

  async function save(e: Event) {
    e.preventDefault();
    saving = true;
    try {
      load(await put<Overview>("/api/platform/backups", values));
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
      load(await post<Overview>("/api/platform/backups/run"));
      notify("A backup will start within 5 minutes. It shows in the list below when it's done.", { kind: "info" });
    } catch (err) {
      notifyError(err, { title: "Couldn't ask for a backup" });
    } finally {
      asking = false;
    }
  }

  const size = (b: number) => (b >= 1_048_576 ? `${(b / 1_048_576).toFixed(1)} MB` : b >= 1024 ? `${Math.round(b / 1024)} KB` : b ? `${b} B` : "—");
  const cycleLabel = $derived(data?.cycles.find((c) => c.days === values.every_days)?.label.toLowerCase() ?? "");
  const lastOk = $derived(data?.runs.find((r) => r.status === "ok"));
  const busy = $derived(!!data?.settings.requested_at || !!data?.runs.some((r) => r.status === "running"));
</script>

<form class="card" onsubmit={save} novalidate>
  <div class="card-header"><div><h2 class="card-title">Backups</h2>
    <p class="card-description">A full copy of the database (every centre's patients, bills and settings), kept on the server. Times are India time.</p></div></div>
  <div class="card-content stack-lg">
    <div class="status" aria-live="polite">
      <div><span class="label">Next backup</span>
        <span class="font-semibold">{!data ? "…" : !data.settings.enabled ? "Scheduled backups are off" : data.settings.next_run_at ? dateTime(data.settings.next_run_at) : "—"}</span></div>
      <div><span class="label">Last good backup</span>
        <span class="font-semibold">{!data ? "…" : lastOk ? `${dateTime(lastOk.finished_at ?? lastOk.started_at)} · ${size(lastOk.size_bytes)}` : "None yet"}</span></div>
    </div>

    <label class="check-row">
      <input type="checkbox" class="checkbox" bind:checked={values.enabled} />
      <span><span class="font-semibold">Back up automatically</span>
        <span class="text-sm text-muted">· when this is off, only "Back up now" makes a backup.</span></span>
    </label>

    <div class="grid-3 fields">
      <Field id="bk_every" label="How often" tip="Every 2 days means the day after a backup is skipped. A week counts from the last scheduled backup.">
        {#snippet children({ describedby })}
          <select id="bk_every" class="select" bind:value={values.every_days} disabled={!values.enabled} aria-describedby={describedby}>
            {#each data?.cycles ?? [] as c (c.days)}<option value={c.days}>{c.label}</option>{/each}
          </select>
        {/snippet}
      </Field>
      <Field id="bk_time" label="At" tip="The backup starts within 5 minutes of this time. Late evening is best: billing is quiet and the day's bills are in.">
        {#snippet children({ describedby })}
          <input id="bk_time" class="input" type="time" step="300" bind:value={values.at_time} disabled={!values.enabled} aria-describedby={describedby} required />
        {/snippet}
      </Field>
      <Field id="bk_keep" label="Keep copies for" tip="Older copies are deleted after each backup, so the server's disk doesn't fill up. Forever: none are deleted.">
        {#snippet children({ describedby })}
          <select id="bk_keep" class="select" bind:value={values.keep_days} aria-describedby={describedby}>
            {#each data?.keep_options ?? [] as k (k.days)}<option value={k.days}>{k.label}</option>{/each}
          </select>
        {/snippet}
      </Field>
    </div>
    {#if values.enabled && data}
      <p class="text-sm text-muted">The database will be backed up {cycleLabel} at {values.at_time}, {values.keep_days === 0 ? "and every copy kept (none deleted; keep an eye on the server's disk)" : `and each copy kept for ${data.keep_options.find((k) => k.days === values.keep_days)?.label}`}.</p>
    {/if}
  </div>
  <div class="card-footer actions">
    <button type="button" class="btn btn-outline" onclick={backUpNow} disabled={!data || asking || busy}>
      <Icon name="download" size="sm" />{busy ? "Backup on its way…" : "Back up now"}
    </button>
    <button type="submit" class="btn btn-primary" disabled={!dirty || saving}>{saving ? "Saving…" : "Save schedule"}</button>
  </div>
</form>

<section class="card" aria-labelledby="bk-runs">
  <div class="card-header"><div><h2 class="card-title" id="bk-runs">Recent backups</h2>
    <p class="card-description">The last 30, newest first. <InfoTip about="where backups are" text="Copies are in /opt/supreme-dms/backups on the server. Restore one with deploy/restore.sh; copy the folder somewhere safe now and then." /></p></div></div>
  <div class="table-wrap">
    <table class="table" style="min-width: 0">
      <thead><tr><th>Started</th><th class="hide-sm">Why</th><th>Result</th><th class="num">Size</th><th class="hide-sm">File</th></tr></thead>
      <tbody>
        {#each data?.runs ?? [] as r (r.id)}
          <tr>
            <td class="tabular">{dateTime(r.started_at)}</td>
            <td class="hide-sm text-sm">{r.trigger === "manual" ? "Asked for" : "Scheduled"}</td>
            <td>
              {#if r.status === "ok"}<span class="badge badge-success"><Icon name="check" size="sm" />Done</span>{#if !r.kept}<span class="text-sm text-muted"> · deleted</span>{/if}
              {:else if r.status === "running"}<span class="badge badge-info"><Icon name="clock" size="sm" />Running</span>
              {:else}<span class="badge badge-destructive"><Icon name="alert" size="sm" />Failed</span><div class="cell-sub">{r.message}</div>{/if}
            </td>
            <td class="num tabular">{size(r.size_bytes)}</td>
            <td class="hide-sm mono text-sm">{r.file || "—"}</td>
          </tr>
        {:else}
          <tr><td colspan="5"><div class="empty"><Icon name="inbox" />{data ? "No backups recorded yet." : "Loading…"}</div></td></tr>
        {/each}
      </tbody>
    </table>
  </div>
</section>

<style>
  .status { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; padding: 12px 14px; border-radius: 10px; background: var(--muted); }
  .status > div { display: flex; flex-direction: column; gap: 2px; }
  .fields { align-items: start; }
  .actions { display: flex; justify-content: flex-end; gap: 10px; flex-wrap: wrap; }
  @media (max-width: 760px) { .hide-sm { display: none; } .fields { grid-template-columns: 1fr !important; } .status { grid-template-columns: 1fr; } }
</style>
