<script lang="ts">
  import Dialog from "../components/Dialog.svelte";
  import Icon from "../components/Icon.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import StatCard from "../components/StatCard.svelte";
  import { tooltip } from "../lib/tooltip";

  // Development only: what the server is doing right now. Requests, errors and slow queries arrive as they happen
  // (GET /api/dev/stream); background jobs, uploads in progress and the database pool every couple of seconds.
  // Each panel can be expanded to fill the screen (the same feed, just with room to read it).
  type Ev = { seq: number; kind: "request" | "error" | "slow_sql"; at: number; [k: string]: any };
  type Stats = { uptime_s: number; per_minute: number; avg_ms: number; p95_ms: number; errors_per_minute: number;
                 requests: number; errors: number; server_errors: number; queries: number; slow_queries: number };
  type System = { jobs?: Record<string, number>; failed_jobs?: { kind: string; error: string; at: string }[];
                  uploads?: { filename: string; purpose: string; received: number; size: number }[];
                  pool?: { size: number; checked_out: number; overflow: number }; error?: string };

  const KEEP = 200;
  let requests = $state<Ev[]>([]);
  let errors = $state<Ev[]>([]);
  let slow = $state<Ev[]>([]);
  let stats = $state<Stats | null>(null);
  let system = $state<System>({});
  let connected = $state(false);
  let paused = $state(false);
  let filter = $state("");
  let onlyProblems = $state(false);

  let expandRequests = $state(false);
  let expandSystem = $state(false);
  let expandErrors = $state(false);
  let expandSlow = $state(false);

  $effect(() => {
    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout>;
    const open = () => {
      source = new EventSource("/api/dev/stream", { withCredentials: true });
      source.onopen = () => (connected = true);
      source.onerror = () => { connected = false; source?.close(); retry = setTimeout(open, 3000); };
      source.addEventListener("reconnect", () => { source?.close(); open(); });
      source.addEventListener("stats", (e) => {
        const d = JSON.parse((e as MessageEvent).data);
        stats = d.stats;
        if (d.system) system = d.system;
      });
      source.addEventListener("events", (e) => {
        if (paused) return;
        const fresh: Ev[] = JSON.parse((e as MessageEvent).data);
        const req = fresh.filter((x) => x.kind === "request").reverse();
        if (req.length) requests = [...req, ...requests].slice(0, KEEP);
        const err = fresh.filter((x) => x.kind === "error").reverse();
        if (err.length) errors = [...err, ...errors].slice(0, KEEP);
        const sql = fresh.filter((x) => x.kind === "slow_sql").reverse();
        if (sql.length) slow = [...sql, ...slow].slice(0, KEEP);
      });
    };
    open();
    return () => { clearTimeout(retry); source?.close(); };
  });

  const shown = $derived(requests.filter((r) => (!onlyProblems || r.status >= 400 || r.ms > 500)
    && (!filter || `${r.method} ${r.path} ${r.status} ${r.tenant ?? ""}`.toLowerCase().includes(filter.toLowerCase()))));
  const time = (at: number) => new Date(at * 1000).toLocaleTimeString([], { hour12: false });
  const tone = (s: number) => (s >= 500 ? "badge-destructive" : s >= 400 ? "badge-warning" : "badge-success");
  const uptime = $derived(stats ? `${Math.floor(stats.uptime_s / 3600)}h ${Math.floor((stats.uptime_s % 3600) / 60)}m` : "—");
</script>

{#snippet expand(label: string, onclick: () => void)}
  <button class="btn btn-ghost btn-icon" type="button" use:tooltip={`Expand ${label}`} aria-label="Expand {label}" {onclick}><Icon name="maximize" /></button>
{/snippet}

{#snippet requestsControls()}
  <input class="input input-sm" placeholder="Filter path, status, client…" bind:value={filter} aria-label="Filter requests" />
  <label class="check-row"><input class="checkbox" type="checkbox" bind:checked={onlyProblems} /> <span>Problems only</span></label>
{/snippet}

{#snippet requestsTable()}
  <table class="table" style="min-width: 0">
    <thead><tr><th>Time</th><th>Request</th><th class="num">Status</th><th class="num">ms</th><th class="num">SQL</th><th>Client</th></tr></thead>
    <tbody>
      {#each shown as r (r.seq)}
        <tr class:slow={r.ms > 500}>
          <td class="mono text-sm nowrap">{time(r.at)}</td>
          <td class="mono text-sm"><span class="method">{r.method}</span> {r.path}</td>
          <td class="num"><span class="badge {tone(r.status)}">{r.status}</span></td>
          <td class="num tabular">{r.ms}</td>
          <td class="num tabular text-sm" title="{r.sql_ms} ms in the database">{r.queries}</td>
          <td class="text-sm text-muted">{r.tenant ?? "—"}</td>
        </tr>
      {:else}
        <tr><td colspan="6" class="text-muted">Waiting for requests… use the app in another tab.</td></tr>
      {/each}
    </tbody>
  </table>
{/snippet}

{#snippet systemBody()}
  {#if system.error}<div class="alert alert-destructive"><Icon name="alert" /><div>{system.error}</div></div>{/if}
  {#if system.pool}
    <div><div class="text-sm text-muted">Database connections</div>
      <div class="font-semibold">{system.pool.checked_out} in use of {system.pool.size}{system.pool.overflow > 0 ? ` (+${system.pool.overflow} extra)` : ""}</div>
      <div class="progress mt-2"><div class="progress-bar" style="width: {Math.min(100, (system.pool.checked_out / Math.max(1, system.pool.size)) * 100)}%"></div></div>
    </div>
  {/if}
  <div><div class="text-sm text-muted">Background jobs</div>
    <div class="row-wrap mt-2">
      {#each Object.entries(system.jobs ?? {}) as [s, n] (s)}<span class="badge {s === 'failed' ? 'badge-destructive' : s === 'running' ? 'badge-info' : 'badge-plain'}">{s} {n}</span>{:else}<span class="text-sm text-muted">None</span>{/each}
    </div>
    {#each system.failed_jobs ?? [] as j, i (i)}<div class="text-sm mt-2"><strong>{j.kind}</strong> <span class="text-muted">{j.error}</span></div>{/each}
  </div>
  <div><div class="text-sm text-muted">Uploads in progress</div>
    {#each system.uploads ?? [] as u, i (i)}
      <div class="text-sm mt-2">{u.filename} <span class="text-muted">({u.purpose})</span></div>
      <div class="progress"><div class="progress-bar" style="width: {Math.floor((u.received / Math.max(1, u.size)) * 100)}%"></div></div>
    {:else}<div class="text-sm text-muted">None</div>{/each}
  </div>
{/snippet}

{#snippet errorsBody()}
  {#each errors as e (e.seq)}
    <div class="entry"><div class="row gap-sm"><span class="badge {e.level === 'ERROR' || e.level === 'CRITICAL' ? 'badge-destructive' : 'badge-warning'}">{e.level}</span>
      <span class="mono text-sm text-muted">{time(e.at)}</span></div>
      <div class="text-sm mt-2">{e.message}</div>{#if e.detail}<div class="mono text-sm text-muted">{e.detail}</div>{/if}
      <div class="mono text-xs text-muted">{e.logger} · {e.request_id}</div></div>
  {:else}<div class="text-sm text-muted">None so far.</div>{/each}
{/snippet}

{#snippet slowBody()}
  {#each slow as q (q.seq)}
    <div class="entry"><div class="row gap-sm"><span class="badge badge-warning">{q.ms} ms</span><span class="mono text-sm text-muted">{time(q.at)}</span></div>
      <div class="mono text-xs mt-2 sql">{q.sql}</div></div>
  {:else}<div class="text-sm text-muted">None so far.</div>{/each}
{/snippet}

<PageHeader eyebrow="Development" title="Dev monitor" description="Live view of the server: requests, errors, slow queries, jobs and uploads. Only in development.">
  {#snippet actions()}
    <span class="badge {connected ? 'badge-success' : 'badge-destructive'}"><span class="dot"></span>{connected ? "Live" : "Reconnecting…"}</span>
    <button class="btn btn-outline" onclick={() => (paused = !paused)}><Icon name={paused ? "play" : "pause"} /> {paused ? "Resume" : "Pause"}</button>
    <button class="btn btn-ghost" onclick={() => { requests = []; errors = []; slow = []; }}><Icon name="trash" /> Clear</button>
  {/snippet}
</PageHeader>

<div class="stat-grid">
  <StatCard label="Requests / min" value={String(stats?.per_minute ?? "—")} note="Last 60 seconds" icon="activity" />
  <StatCard label="Average / p95" value={stats ? `${stats.avg_ms} / ${stats.p95_ms} ms` : "—"} note="Response time, last minute" icon="clock" />
  <StatCard label="Errors / min" value={String(stats?.errors_per_minute ?? "—")} note={stats ? `${stats.server_errors} server errors since start` : ""} icon="alert" tone={stats && stats.errors_per_minute > 0 ? "red" : ""} />
  <StatCard label="SQL queries" value={String(stats?.queries ?? "—")} note={stats ? `${stats.slow_queries} slow (≥ 50 ms) · up ${uptime}` : ""} icon="layers" tone={stats && stats.slow_queries > 0 ? "orange" : ""} />
</div>

<div class="grid-3 items-start mt-4">
  <section class="card span-2" aria-labelledby="req-title">
    <div class="card-header"><div><h2 class="card-title" id="req-title">Requests</h2>
      <p class="card-description">Newest first · {requests.length} kept</p></div>
      <div class="row gap-sm">
        {@render requestsControls()}
        {@render expand("Requests", () => (expandRequests = true))}
      </div>
    </div>
    <div class="card-flush"><div class="table-wrap feed">{@render requestsTable()}</div></div>
  </section>

  <div class="stack">
    <section class="card" aria-labelledby="sys-title">
      <div class="card-header"><div><h2 class="card-title" id="sys-title">System</h2></div>{@render expand("System", () => (expandSystem = true))}</div>
      <div class="card-content stack">{@render systemBody()}</div>
    </section>

    <section class="card" aria-labelledby="err-title">
      <div class="card-header"><div><h2 class="card-title" id="err-title">Errors and warnings</h2><p class="card-description">{errors.length} kept</p></div>
        {@render expand("Errors and warnings", () => (expandErrors = true))}</div>
      <div class="card-content stack feed-sm">{@render errorsBody()}</div>
    </section>

    <section class="card" aria-labelledby="sql-title">
      <div class="card-header"><div><h2 class="card-title" id="sql-title">Slow queries</h2><p class="card-description">50 ms or more, without their values</p></div>
        {@render expand("Slow queries", () => (expandSlow = true))}</div>
      <div class="card-content stack feed-sm">{@render slowBody()}</div>
    </section>
  </div>
</div>

<Dialog bind:open={expandRequests} title="Requests" description="{requests.length} kept · newest first" full>
  <div class="row gap-sm mb-3">{@render requestsControls()}</div>
  <div class="table-wrap">{@render requestsTable()}</div>
</Dialog>
<Dialog bind:open={expandSystem} title="System" description="Database pool, background jobs and uploads in progress" full>
  <div class="stack">{@render systemBody()}</div>
</Dialog>
<Dialog bind:open={expandErrors} title="Errors and warnings" description="{errors.length} kept" full>
  <div class="stack">{@render errorsBody()}</div>
</Dialog>
<Dialog bind:open={expandSlow} title="Slow queries" description="50 ms or more, without their values" full>
  <div class="stack">{@render slowBody()}</div>
</Dialog>

<style src="./styles/DevMonitor.css"></style>
