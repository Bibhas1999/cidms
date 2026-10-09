<script lang="ts">
  import type { Snippet } from "svelte";
  import { session } from "../lib/session.svelte";

  // The sign-in, forgot-password and reset-password pages: the centre's branded panel beside a form card.
  let { children }: { children: Snippet } = $props();

  const ws = $derived(session.workspace);
  const isPlatform = $derived(ws?.kind === "platform");
  // Each centre's own colour; the platform uses the product's.
  const brand = $derived(ws?.brand_color || "#1250a6");
</script>

<div class="page" style="--brand: {brand}">
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
        {#if ws?.logo_url}
          <img class="logo" src={ws.logo_url} alt="{ws.name} logo" />
        {:else}
          <svg class="mark" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8" fill="#fff" fill-opacity=".14" />
            <path d="M8 17h4.5l2-6 3 11 2-5H24" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" /></svg>
        {/if}
        <div>
          <h1 class="centre">{isPlatform ? "Supreme DMS" : ws?.name}</h1>
          <p class="tagline">{isPlatform ? "Platform administration" : ws?.tagline || "Diagnostics, reports and billing in one place"}</p>
        </div>
      </div>

      <div class="pitch">
        {#if isPlatform}
          <p class="headline">Every centre, one platform.</p>
          <p class="sub">Clients, plans and support for every diagnostic centre on Supreme DMS.</p>
        {:else}
          <p class="headline">Bills, reports and scans, together for every patient.</p>
          <p class="sub">From the front desk to the reporting room: register, bill, scan, report and deliver without paper.</p>
        {/if}
      </div>

      {#if !isPlatform}
        <ul class="services" aria-label="Services">
          <li>
            <svg viewBox="0 0 40 40" aria-hidden="true"><rect x="7" y="5" width="26" height="30" rx="4" /><path d="M20 10v20M14 14c4 1 8 1 12 0M13 19c5 1.5 9 1.5 14 0M14 24c4 1 8 1 12 0" /></svg>
            <span>Digital X-ray</span>
          </li>
          <li>
            <svg viewBox="0 0 40 40" aria-hidden="true"><circle cx="20" cy="18" r="13" /><circle cx="20" cy="18" r="6" /><path d="M8 34h24M13 34l3-6h8l3 6" /></svg>
            <span>CT scan</span>
          </li>
          <li>
            <svg viewBox="0 0 40 40" aria-hidden="true"><path d="M10 30c0-9 4-17 10-17s10 8 10 17z" /><path d="M20 13V6M16 6h8M15 24c2 2 8 2 10 0" /></svg>
            <span>Ultrasound &amp; echo</span>
          </li>
          <li>
            <svg viewBox="0 0 40 40" aria-hidden="true"><path d="M17 5h6M18 5v6l-6 12a6 6 0 0 0 5 9h6a6 6 0 0 0 5-9l-6-12V5" /><path d="M14 23h12" /></svg>
            <span>Pathology</span>
          </li>
          <li>
            <svg viewBox="0 0 40 40" aria-hidden="true"><path d="M4 21h8l3-8 5 16 4-11 3 3h9" /></svg>
            <span>ECG</span>
          </li>
        </ul>
      {/if}

      <p class="powered">Powered by <strong>Supreme DMS</strong></p>
    </div>
  </section>

  <section class="form-side">
    {@render children()}
    <p class="secure muted">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 5 6v6c0 4 3 7.5 7 9 4-1.5 7-5 7-9V6z" /><path d="m9 12 2 2 4-4" /></svg>
      Patient information is kept private and every sign-in is recorded.
    </p>
  </section>
</div>

<style>
  .page { min-height: 100vh; display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(380px, 1fr); background: var(--bg); }

  /* ---------- the centre's side ---------- */
  .brand-panel { position: relative; overflow: hidden; color: #fff;
    background: linear-gradient(150deg, var(--brand) 0%, color-mix(in srgb, var(--brand) 72%, #0b2f6b) 100%); }
  .backdrop { position: absolute; inset: 0; width: 100%; height: 100%; }
  .brand-content { position: relative; height: 100%; display: flex; flex-direction: column; gap: 40px; padding: 56px 56px 32px; }
  .identity { display: flex; align-items: center; gap: 22px; }
  .logo { width: 132px; height: auto; border-radius: 14px; box-shadow: 0 10px 30px rgb(0 0 0 / 25%); background: var(--brand); }
  .mark { width: 72px; height: 72px; }
  .centre { font-size: 32px; font-weight: 700; letter-spacing: -.01em; line-height: 1.15; }
  .tagline { margin: 8px 0 0; font-size: 16px; opacity: .85; letter-spacing: .02em; }
  .pitch { margin-top: auto; max-width: 520px; }
  .headline { margin: 0; font-size: 34px; line-height: 1.2; font-weight: 700; letter-spacing: -.015em; }
  .sub { margin: 14px 0 0; font-size: 16px; line-height: 1.55; opacity: .82; }
  .services { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; max-width: 560px; }
  .services li { display: flex; align-items: center; gap: 12px; padding: 12px 14px; border-radius: 12px;
    background: rgb(255 255 255 / 9%); border: 1px solid rgb(255 255 255 / 14%); font-weight: 550; }
  .services svg { width: 30px; height: 30px; flex: none; fill: none; stroke: #fff; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
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
  .form-side :global(.control input) { height: 44px; padding-left: 40px; font-weight: 400; font-size: 15px; }
  .form-side :global(.control input:focus) { outline-color: var(--brand); }
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
  .secure svg { width: 16px; height: 16px; fill: none; stroke: var(--success); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }

  @media (max-width: 900px) {
    .page { grid-template-columns: 1fr; }
    .brand-content { padding: 28px 20px; gap: 0; }
    .logo { width: 72px; border-radius: 10px; }
    .centre { font-size: 22px; }
    .tagline { font-size: 14px; }
    .services, .powered, .pitch { display: none; }
    .form-side { padding: 24px 16px 32px; justify-content: flex-start; }
    .form-side :global(.form) { padding: 28px 20px; }
  }
  @media (prefers-reduced-motion: reduce) { .form-side :global(.spinner) { animation: none; } }
</style>
