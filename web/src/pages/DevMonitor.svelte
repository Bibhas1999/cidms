<script lang="ts">
  import Icon from "../components/Icon.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import StatCard from "../components/StatCard.svelte";

  // Development only: what the server is doing right now. Requests, errors and slow queries arrive as they happen
  // (GET /api/dev/stream); background jobs, uploads in progress and the database pool every couple of seconds.
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

<PageHeader eyebrow="Development" title="Dev monitor" description="Live view of the server: requests, errors, slow queries, jobs and uploads. Only in development.">
  {#snippet actions()}
    <span class="badge {connected ? 'badge-success' : 'badge-destructive'}"><span class="dot"></span>{connected ? "Live" : "Reconnecting…"}</span>
    <button class="btn btn-outline" onclick={() => (paused = !paused)}><Icon name={paused ? "play" : "pause"} /> {paused ? "Resume" : "Pause"}</button>
    <button class="btn btn-ghost" onclick={() => { requests = []; errors = []; slow = []; }}><Icon name="trash" /> Clear</button>
  {/snippet}
</PageHeader>

<div class="stat-grid">
  <StatCard label="Requests / min" value={String(stats?.per_minute ?? "—")} note="Last 60 seconds" />
  <StatCard label="Average / p95" value={stats ? `${stats.avg_ms} / ${stats.p95_ms} ms` : "—"} note="Response time, last minute" />
  <StatCard label="Errors / min" value={String(stats?.errors_per_minute ?? "—")} note={stats ? `${stats.server_errors} server errors since start` : ""} />
  <StatCard label="SQL queries" value={String(stats?.queries ?? "—")} note={stats ? `${stats.slow_queries} slow (≥ 50 ms) · up ${uptime}` : ""} />
</div>

<div class="grid-3 items-start mt-4">
  <section class="card span-2" aria-labelledby="req-title">
    <div class="card-header"><div><h2 class="card-title" id="req-title">Requests</h2>
      <p class="card-description">Newest first · {requests.length} kept</p></div>
      <div class="row gap-sm">
        <input class="input input-sm" placeholder="Filter path, status, client…" bind:value={filter} aria-label="Filter requests" />
        <label class="check-row"><input class="checkbox" type="checkbox" bind:checked={onlyProblems} /> <span>Problems only</span></label>
      </div>
    </div>
    <div class="card-flush"><div class="table-wrap feed"><table class="table" style="min-width: 0">
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
    </table></div></div>
  </section>

  <div class="stack">
    <section class="card" aria-labelledby="sys-title">
      <div class="card-header"><div><h2 class="card-title" id="sys-title">System</h2></div></div>
      <div class="card-content stack">
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
      </div>
    </section>

    <section class="card" aria-labelledby="err-title">
      <div class="card-header"><div><h2 class="card-title" id="err-title">Errors and warnings</h2><p class="card-description">{errors.length} kept</p></div></div>
      <div class="card-content stack feed-sm">
        {#each errors as e (e.seq)}
          <div class="entry"><div class="row gap-sm"><span class="badge {e.level === 'ERROR' || e.level === 'CRITICAL' ? 'badge-destructive' : 'badge-warning'}">{e.level}</span>
            <span class="mono text-sm text-muted">{time(e.at)}</span></div>
            <div class="text-sm mt-2">{e.message}</div>{#if e.detail}<div class="mono text-sm text-muted">{e.detail}</div>{/if}
            <div class="mono text-xs text-muted">{e.logger} · {e.request_id}</div></div>
        {:else}<div class="text-sm text-muted">None so far.</div>{/each}
      </div>
    </section>

    <section class="card" aria-labelledby="sql-title">
      <div class="card-header"><div><h2 class="card-title" id="sql-title">Slow queries</h2><p class="card-description">50 ms or more, without their values</p></div></div>
      <div class="card-content stack feed-sm">
        {#each slow as q (q.seq)}
          <div class="entry"><div class="row gap-sm"><span class="badge badge-warning">{q.ms} ms</span><span class="mono text-sm text-muted">{time(q.at)}</span></div>
            <div class="mono text-xs mt-2 sql">{q.sql}</div></div>
        {:else}<div class="text-sm text-muted">None so far.</div>{/each}
      </div>
    </section>
  </div>
</div>

<style>
  .stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }
  .feed { max-height: 65vh; overflow: auto; }
  .feed-sm { max-height: 320px; overflow: auto; }
  .method { font-weight: 700; }
  tr.slow td { background: color-mix(in srgb, var(--warning, #f59e0b) 10%, transparent); }
  .entry { padding-bottom: 8px; border-bottom: 1px solid var(--border); }
  .sql { word-break: break-word; white-space: pre-wrap; }
  .text-xs { font-size: 11.5px; }
  .dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: currentColor; margin-right: 6px; }
</style>
