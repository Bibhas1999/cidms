<script lang="ts">
  import Credit from "../components/Credit.svelte";
  import Icon from "../components/Icon.svelte";
  import type { Workspace } from "../lib/types";

  // The product's own page, at the bare address (cidms.duckdns.org) and at a centre address that doesn't exist
  // (a typo): what CIDMS is, a box to go to your centre, and the way to the platform. Lists no centres.
  let { ws }: { ws: Workspace } = $props();

  const base = $derived(ws.base_domain || location.hostname);
  const port = location.port ? `:${location.port}` : "";
  const here = location.hostname.toLowerCase();
  // A sub-address that isn't a centre: "supremee" in supremee.cidms.duckdns.org
  const typo = $derived(here !== base && here.endsWith(`.${base}`) ? here.slice(0, -base.length - 1) : "");
  let slug = $state("");
  let problem = $state("");
  const go = (e: Event) => {
    e.preventDefault();
    const s = slug.trim().toLowerCase().replace(/\s+/g, "");
    if (!/^[a-z][a-z0-9-]{1,38}[a-z0-9]$/.test(s)) { problem = "Type the first part of your centre's address, e.g. supreme."; return; }
    location.href = `${location.protocol}//${s}.${base}${port}/login`;
  };
  const platform = $derived(`${location.protocol}//${ws.platform_subdomain || "admin"}.${base}${port}/login`);

  const FEATURES = [
    { icon: "receipt", title: "Billing and dues", text: "Fast bills with tests, discounts and payments; dues tracked to the last rupee; old-style printed bills." },
    { icon: "barChart", title: "Reports and analytics", text: "Collection, dues, tests, doctors and staff as Excel-style sheets; Excel, PDF and print." },
    { icon: "bell", title: "Notifications", text: "Cancellations, refunds, big discounts and a daily summary, in the app or as browser pop-ups." },
    { icon: "shield", title: "Roles and permissions", text: "Each person sees only what their job needs; every sign-in and change is recorded." },
    { icon: "monitor", title: "Works everywhere", text: "On the desk computer, a tablet or a phone; install it like an app." },
    { icon: "lock", title: "Private by design", text: "Every centre has its own workspace; one centre can never see another's patients or bills." },
  ];
</script>

<div class="landing">
  <header class="hero">
    <span class="mark" aria-hidden="true">
      <Icon name="brandMark" />
    </span>
    <h1>CIDMS</h1>
    <p class="full">Cloud Integrated Diagnostic Management System</p>
    <p class="lead">Billing, dues, reports and analytics for diagnostic centres, clinics and OPDs — in one secure, cloud-based workspace for each centre.</p>
  </header>

  <section class="card goto" aria-labelledby="goto-title">
    {#if typo}
      <div class="alert alert-warning" role="status"><Icon name="alert" /><div><div class="alert-title">No centre at “{typo}”</div>Check the spelling of your centre's address.</div></div>
    {/if}
    <h2 id="goto-title">Go to your centre</h2>
    <form class="goto-row" onsubmit={go} novalidate>
      <label class="sr-only" for="slug">Your centre's address</label>
      <div class="addr" class:is-invalid={!!problem}>
        <span class="addr-pre">https://</span>
        <input id="slug" class="addr-input" bind:value={slug} placeholder="yourcentre" autocomplete="off" autocapitalize="none" spellcheck="false"
               aria-invalid={!!problem} aria-describedby="slug-help" oninput={() => (problem = "")} />
        <span class="addr-post">.{base}</span>
      </div>
      <button class="btn btn-primary" type="submit">Open <Icon name="arrowRight" size="sm" /></button>
    </form>
    <p id="slug-help" class={problem ? "field-error" : "hint"}>{problem || "Your centre's address was given to you when it joined CIDMS, e.g. supreme."}</p>
  </section>

  <section class="features" aria-label="What CIDMS does">
    {#each FEATURES as f (f.title)}
      <div class="feature card"><span class="f-icon"><Icon name={f.icon} /></span><div><h3>{f.title}</h3><p>{f.text}</p></div></div>
    {/each}
  </section>

  {#if ws.links?.length}
    <section class="card dev" aria-label="On this computer">
      <p class="text-sm text-muted">On this computer (development only):</p>
      <ul>{#each ws.links as link (link.url)}<li><a href={link.url}>{link.name}</a> <span class="text-muted mono text-sm">{link.url}</span></li>{/each}</ul>
    </section>
  {/if}

  <footer class="foot">
    <a href={platform}>Platform sign-in</a><span aria-hidden="true">·</span><a href="/terms">Terms and conditions</a><span aria-hidden="true">·</span><Credit />
  </footer>
</div>

<style src="./styles/Landing.css"></style>
