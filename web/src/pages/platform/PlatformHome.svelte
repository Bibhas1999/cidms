<script lang="ts">
  import KpiCard from "../../components/charts/KpiCard.svelte";
  import Icon from "../../components/Icon.svelte";
  import { get } from "../../lib/api";
  import { count, date, rupees } from "../../lib/format";
  import { navigate } from "../../lib/router.svelte";
  import { session } from "../../lib/session.svelte";
  import { tooltip } from "../../lib/tooltip";

  // The platform's home: every centre at a glance — how many, who's on them, how much they're used this month,
  // and whose subscription needs renewing. Counts only: what a centre bills is its own business.
  interface Row {
    id: string; slug: string; name: string; kind: string; status: string; plan: string | null; paid_until: string | null;
    created_at: string; staff: number; bills_this_month: number; bill_limit: number | null; usage_pct: number | null;
  }
  interface Overview {
    centres: number; active: number; suspended: number; by_kind: Record<string, number>; staff: number; platform_staff: number;
    bills_this_month: number; plan_value_monthly: string; renewals: Row[]; overdue: number; centres_list: Row[];
  }

  let data = $state<Overview | null>(null);
  let failed = $state("");
  $effect(() => { get<Overview>("/api/platform/overview").then((d) => (data = d)).catch((e) => (failed = e.message)); });

  const KIND: Record<string, string> = { diagnostic: "Diagnostic centre", opd: "OPD", clinic: "Clinic" };
  const host = typeof location === "undefined" ? "" : location.host.replace(/^admin\./, "");
  const centreUrl = (slug: string) => `${location.protocol}//${slug}.${host}`;
  const overdue = (r: Row) => !!r.paid_until && new Date(r.paid_until) < new Date();
</script>

{#if failed}
  <div class="alert alert-destructive" role="alert"><Icon name="alert" /><div><div class="alert-title">Couldn't load the overview</div>{failed}</div></div>
{/if}

<div class="grid-4 kpis" aria-busy={!data}>
  <KpiCard icon="building" href="/clients" label="Centres" loading={!data} value={data ? count(data.centres) : ""}
           tip="Centres on CIDMS: diagnostic centres, clinics and OPDs. Suspended ones can't sign in."
           note={data ? `${count(data.active)} active${data.suspended ? ` · ${count(data.suspended)} suspended` : ""}` : ""} />
  <KpiCard icon="users" label="Staff accounts" loading={!data} value={data ? count(data.staff) : ""}
           tip="Active staff accounts across all centres, and the platform's own team."
           note={data ? `${count(data.platform_staff)} platform staff` : ""} />
  <KpiCard icon="receipt" label="Bills this month" loading={!data} value={data ? count(data.bills_this_month) : ""}
           tip="How many bills all centres made this month: a measure of use, compared with each plan's limit below." />
  <KpiCard icon="wallet" tone="green" href="/clients" label="Plan value" loading={!data}
           value={data ? rupees(data.plan_value_monthly, { paise: false }) : ""}
           tip="What the active centres' plans come to each month, at list price."
           note={data ? (data.overdue ? `${count(data.overdue)} renewal${data.overdue === 1 ? "" : "s"} overdue` : "a month, active centres") : ""} />
</div>

<div class="grid-3 items-start">
  <section class="card span-2" aria-labelledby="centres-title">
    <div class="card-header">
      <div><h2 class="card-title" id="centres-title">Centres</h2><p class="card-description">Newest first, with their use this month.</p></div>
      {#if session.can("platform.clients.view")}<a class="btn btn-ghost btn-sm" href="/clients">All centres <Icon name="arrowRight" size="sm" /></a>{/if}
    </div>
    <div class="table-wrap">
      <table class="table" style="min-width: 0">
        <thead><tr><th>Centre</th><th class="hide-sm">Plan</th><th class="num">Staff</th><th>Bills this month</th><th class="num"><span class="sr-only">Open</span></th></tr></thead>
        <tbody>
          {#each data?.centres_list ?? [] as c (c.id)}
            <tr class="is-clickable" onclick={(e) => { if (!(e.target as Element).closest("a")) navigate(`/clients?search=${encodeURIComponent(c.slug)}`); }}>
              <td><div class="cell-title">{c.name}</div>
                <div class="cell-sub">{KIND[c.kind] ?? c.kind}{#if c.status !== "active"} · <span class="badge badge-destructive badge-plain">{c.status}</span>{/if}</div></td>
              <td class="hide-sm text-sm">{c.plan ?? "—"}</td>
              <td class="num tabular">{count(c.staff)}</td>
              <td>
                <div class="usage"><span class="tabular">{count(c.bills_this_month)}{c.bill_limit ? ` / ${count(c.bill_limit)}` : ""}</span>
                  {#if c.usage_pct !== null}<div class="progress" aria-hidden="true"><div class="progress-bar" class:is-high={c.usage_pct >= 90} style="width: {Math.min(100, c.usage_pct)}%"></div></div>{/if}</div>
              </td>
              <td class="num"><a class="btn btn-ghost btn-icon btn-sm" href={centreUrl(c.slug)} target="_blank" rel="noopener"
                                 aria-label="Open {c.name}'s workspace" use:tooltip={`Open ${c.slug}.${host}`}><Icon name="arrowRight" size="sm" /></a></td>
            </tr>
          {:else}
            <tr><td colspan="5"><div class="empty"><Icon name="building" />{data ? "No centres yet. Add the first one in Centres." : "Loading…"}</div></td></tr>
          {/each}
        </tbody>
      </table>
    </div>
  </section>

  <section class="card" aria-labelledby="renew-title">
    <div class="card-header"><div><h2 class="card-title" id="renew-title">Renewals</h2><p class="card-description">Due in the next 30 days, or with no paid-until date.</p></div></div>
    <div class="card-content">
      {#if data?.renewals.length}
        <ul class="renewals">
          {#each data.renewals as r (r.id)}
            <li><span class="cell-title">{r.name}</span>
              <span class="text-sm" class:money-due={overdue(r)}>{r.paid_until ? `${overdue(r) ? "Overdue since" : "Due"} ${date(r.paid_until)}` : "No paid-until date"}</span></li>
          {/each}
        </ul>
      {:else}<div class="empty"><Icon name="check" />{data ? "Nothing due in the next 30 days." : "Loading…"}</div>{/if}
    </div>
  </section>
</div>

<div class="quick-actions">
  {#if session.can("platform.clients.view")}<a class="quick-action" href="/clients"><span class="qa-icon"><Icon name="building" /></span><span>Centres<small>Add a centre, change plans and status</small></span></a>{/if}
  <a class="quick-action" href="/settings/staff"><span class="qa-icon"><Icon name="users" /></span><span>Platform staff<small>Who runs the platform</small></span></a>
  <a class="quick-action" href="/settings/activity"><span class="qa-icon"><Icon name="activity" /></span><span>Activity log<small>Sign-ins and changes</small></span></a>
  <a class="quick-action" href="/settings"><span class="qa-icon"><Icon name="settings" /></span><span>Settings<small>Your account and preferences</small></span></a>
</div>

<style>
  .usage { display: flex; flex-direction: column; gap: 4px; min-width: 120px; }
  .usage .progress { height: 5px; }
  .progress-bar.is-high { background: var(--destructive); }
  .renewals { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
  .renewals li { display: flex; justify-content: space-between; gap: 12px; padding: 9px 0; border-bottom: 1px solid var(--border); }
  .renewals li:last-child { border-bottom: 0; }
  @media (max-width: 760px) { .hide-sm { display: none; } .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; } }
</style>
