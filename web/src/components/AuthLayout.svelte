<script lang="ts">
  import Icon from "./Icon.svelte";
  import type { Snippet } from "svelte";
  import { session } from "../lib/session.svelte";
  import Credit from "./Credit.svelte";

  // The sign-in, forgot-password and reset-password pages: the centre's branded panel beside a form card.
  let { children }: { children: Snippet } = $props();

  const ws = $derived(session.workspace);
  const isPlatform = $derived(ws?.kind === "platform");
  // Each centre's own colour; the platform uses the product's.
  const brand = $derived(ws?.brand_color || "#004aad");
  // admin.cidms.example -> supreme.cidms.example, for the "centre staff sign in elsewhere" hint
  const centreExample = $derived(typeof location === "undefined" ? "" : `yourcentre.${location.host.replace(/^admin\./, "")}`);
</script>

<div class="auth-page" style="--brand: {brand}">
  <!-- The centre's side: its logo, name and what it does. Decorative drawings are hidden from screen readers. -->
  <section class="brand-panel">
    <svg class="backdrop" viewBox="0 0 800 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <defs>
        <pattern id="dots" width="28" height="28" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.4" fill="#fff" opacity=".09" /></pattern>
      </defs>
      <rect width="800" height="900" fill="url(#dots)" />
      <!-- a CT gantry ring -->
      <circle cx="690" cy="170" r="190" fill="none" stroke="#fff" stroke-opacity=".07" stroke-width="46" />
      <circle cx="690" cy="170" r="110" fill="none" stroke="#fff" stroke-opacity=".06" stroke-width="2" />
      <!-- a heartbeat line across the panel -->
      <path d="M0 300 H210 l26 -60 30 120 26 -170 34 220 24 -110 H520 l18 -30 18 30 H800" fill="none" stroke="#fff" stroke-opacity=".16" stroke-width="3" stroke-linejoin="round" />
    </svg>

    <div class="brand-content">
      <div class="identity">
        {#if !isPlatform && ws?.wordmark_url}
          <div class="wordmark-tile"><img class="wordmark" src={ws.wordmark_url} alt="{ws.name}{ws.tagline ? ` — ${ws.tagline}` : ''}" /></div>
          <h1 class="sr-only">{ws.name}</h1>
        {:else}
        {#if ws?.logo_url}
          <img class="logo" src={ws.logo_url} alt="{ws.name} logo" />
        {:else}
          <Icon name="brandMark" class="mark" />
        {/if}
        <div>
          <h1 class="centre">{isPlatform ? "CIDMS" : ws?.name}</h1>
          <p class="tagline">{isPlatform ? "Cloud Integrated Diagnostic Management System" : ws?.tagline || "Diagnostics, reports and billing in one place"}</p>
        </div>
        {/if}
      </div>

      <div class="pitch">
        {#if isPlatform}
          <p class="headline">Every centre, one platform.</p>
          <p class="sub">The CIDMS administration: add diagnostic centres, clinics and OPDs, manage their plans and subscriptions,
            and look after their accounts. Each centre works in its own private workspace.</p>
        {:else}
          <p class="headline">Bills, reports and scans, together for every patient.</p>
          <p class="sub">From the front desk to the reporting room: register, bill, scan, report and deliver without paper.</p>
        {/if}
      </div>

      {#if isPlatform}
        <ul class="services" aria-label="What the platform does">
          <li>
            <Icon name="svcCentres" />
            <span>Centres and plans</span>
          </li>
          <li>
            <Icon name="svcSubscriptions" />
            <span>Subscriptions</span>
          </li>
          <li>
            <Icon name="svcStaff" />
            <span>Platform staff</span>
          </li>
          <li>
            <Icon name="svcSecurity" />
            <span>Security and activity</span>
          </li>
        </ul>
      {:else}
        <ul class="services" aria-label="Services">
          <li>
            <Icon name="svcXray" />
            <span>Digital X-ray</span>
          </li>
          <li>
            <Icon name="svcCt" />
            <span>CT scan</span>
          </li>
          <li>
            <Icon name="svcUltrasound" />
            <span>Ultrasound &amp; echo</span>
          </li>
          <li>
            <Icon name="svcPathology" />
            <span>Pathology</span>
          </li>
          <li>
            <Icon name="svcEcg" />
            <span>ECG</span>
          </li>
        </ul>
      {/if}

      <p class="powered"><Credit inherit /></p>
    </div>
  </section>

  <section class="form-side">
    {@render children()}
    <p class="secure muted">
      <Icon name="shieldCheck" />
      Patient information is kept private and every sign-in is recorded.
    </p>
    {#if isPlatform}
      <p class="terms muted">This is the platform administration. Centre staff sign in at their centre's own address,
        e.g. <span class="mono">{centreExample}</span>.</p>
    {/if}
    <p class="terms muted">By signing in you agree to the <a href="/terms">Terms and conditions</a>.</p>
  </section>
</div>

<style src="./styles/AuthLayout.css"></style>
