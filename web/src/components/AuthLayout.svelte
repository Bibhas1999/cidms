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

<style>
  .auth-page { min-height: 100vh; display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(380px, 1fr); background: var(--bg); }

  /* ---------- the centre's side ---------- */
  .brand-panel { position: relative; overflow: hidden; color: #fff;
    background: linear-gradient(150deg, var(--brand) 0%, color-mix(in srgb, var(--brand) 72%, #0b2f6b) 100%); }
  .backdrop { position: absolute; inset: 0; width: 100%; height: 100%; }
  .brand-content { position: relative; height: 100%; display: flex; flex-direction: column; gap: 40px; padding: 56px 56px 32px; }
  .identity { display: flex; align-items: center; gap: 22px; }
  .wordmark-tile { display: inline-block; max-width: 100%; padding: 14px 20px; border-radius: 18px; background: #fff; box-shadow: 0 10px 30px rgb(0 0 0 / 25%); }
  .wordmark { display: block; width: 400px; max-width: 100%; height: auto; }
  .logo { width: 132px; height: 132px; object-fit: contain; padding: 10px; border-radius: 18px; background: #fff; box-shadow: 0 10px 30px rgb(0 0 0 / 25%); }
  .brand-panel :global(svg.mark) { width: 72px; height: 72px; color: #fff; }
  .centre { color: #fff; font-size: 32px; font-weight: 700; letter-spacing: -.01em; line-height: 1.15; }
  .tagline { margin: 8px 0 0; font-size: 16px; opacity: .85; letter-spacing: .02em; }
  .pitch { margin-top: auto; max-width: 520px; }
  .headline { color: #fff; margin: 0; font-size: 34px; line-height: 1.2; font-weight: 700; letter-spacing: -.015em; }
  .sub { margin: 14px 0 0; font-size: 16px; line-height: 1.55; opacity: .82; }
  .services { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; max-width: 560px; }
  .services li { display: flex; align-items: center; gap: 12px; padding: 12px 14px; border-radius: 12px;
    background: rgb(255 255 255 / 9%); border: 1px solid rgb(255 255 255 / 14%); font-weight: 550; }
  .services :global(svg.icon) { width: 30px; height: 30px; flex: none; fill: none; stroke: #fff; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
  .powered { margin: 0; font-size: 13px; opacity: .7; }

  /* ---------- the form side (shared by sign-in, forgot and reset) ---------- */
  .form-side { display: flex; flex-direction: column; justify-content: center; align-items: center; padding: 40px 24px; gap: 20px; }
  .form-side :global(.form) { width: min(400px, 100%); display: grid; gap: 18px; padding: 36px 32px; background: var(--surface);
    border: 1px solid var(--border); border-radius: 16px; box-shadow: 0 1px 3px rgb(16 24 40 / 8%), 0 20px 40px -12px rgb(16 24 40 / 18%); }
  .form-side :global(.heading h2) { font-size: 24px; }
  .form-side :global(.heading p) { margin: 6px 0 0; }
  .form-side :global(.field) { display: grid; gap: 6px; font-weight: 550; font-size: 13px; }
  .form-side :global(.control) { position: relative; display: flex; align-items: center; }
  .form-side :global(.control > svg) { position: absolute; left: 12px; width: 18px; height: 18px; fill: none; stroke: var(--text-2);
    stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; pointer-events: none; }
  .form-side :global(.control input) { width: 100%; height: 38px; padding: 6px 12px 6px 40px; font: 400 14px var(--font-sans); color: var(--foreground);
    background: var(--background); border: 1px solid var(--input); border-radius: var(--radius-sm); }
  .form-side :global(.control input::placeholder) { color: var(--faint-foreground); }
  .form-side :global(.field label) { font-weight: 600; font-size: 13px; color: var(--foreground); }
  .form-side :global(.heading h2) { color: var(--foreground); }
  .form-side :global(.submit) { height: 46px; border: 0; border-radius: 10px; background: var(--brand); color: #fff; font: inherit; font-size: 15px;
    font-weight: 650; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; gap: 10px; transition: filter .15s, transform .05s; }
  .form-side :global(.submit:hover:not(:disabled)) { filter: brightness(1.12); }
  .form-side :global(.submit:active:not(:disabled)) { transform: translateY(1px); }
  .form-side :global(.submit:disabled) { opacity: .7; cursor: not-allowed; }
  .form-side :global(.spinner) { width: 16px; height: 16px; border-radius: 50%; border: 2px solid rgb(255 255 255 / 40%); border-top-color: #fff;
    animation: auth-spin .7s linear infinite; }
  .form-side :global(.help) { margin: 0; font-size: 12px; text-align: center; }
  .form-side :global(.back) { color: var(--brand); font-weight: 600; text-decoration: none; text-align: center; font-size: 13px; }
  .form-side :global(.back:hover) { text-decoration: underline; }
  @keyframes -global-auth-spin { to { transform: rotate(360deg); } }
  .secure { display: flex; align-items: center; gap: 8px; font-size: 12px; margin: 0; }
  .secure :global(svg.icon) { width: 16px; height: 16px; fill: none; stroke: var(--success); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }

  @media (max-width: 900px) {
    .auth-page { grid-template-columns: 1fr; }
    .brand-content { padding: 28px 20px; gap: 0; }
    .logo { width: 72px; height: 72px; padding: 6px; border-radius: 12px; }
    .wordmark-tile { padding: 10px 14px; border-radius: 12px; }
    .wordmark { width: 280px; }
    .centre { font-size: 22px; }
    .tagline { font-size: 14px; }
    .services, .pitch { display: none; }
    .form-side { padding: 24px 16px 32px; justify-content: flex-start; }
    .form-side :global(.form) { padding: 28px 20px; }
  }
  @media (prefers-reduced-motion: reduce) { .form-side :global(.spinner) { animation: none; } }
  .terms { margin: 10px 0 0; font-size: 12.5px; text-align: center; }
  .terms a { color: inherit; text-decoration: underline; text-underline-offset: 2px; }
</style>
