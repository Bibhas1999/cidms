<script lang="ts">
  import { session } from "../lib/session.svelte";

  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
</script>

<div class="stack">
  <h1>{greeting}, {session.me?.full_name.split(" ")[0]}</h1>

  {#if session.isPlatform}
    <div class="grid">
      {#if session.can("platform.clients.view")}
        <a class="card tile" href="/clients"><h2>Clients</h2><p class="muted">Add centres, change plans, suspend or reactivate.</p></a>
      {/if}
      {#if session.can("platform.staff.manage")}
        <a class="card tile" href="/staff"><h2>Platform staff</h2><p class="muted">Who can run the platform.</p></a>
      {/if}
      {#if session.can("platform.activity.view")}
        <a class="card tile" href="/activity"><h2>Activity log</h2><p class="muted">Every platform sign-in and change.</p></a>
      {/if}
    </div>
  {:else}
    <div class="alert info">
      Supreme DMS is being set up for {session.workspace?.name}. Billing, payments and dues come next, followed by
      reports, imaging and OPD.
    </div>
    <div class="grid">
      {#if session.can("staff.manage")}
        <a class="card tile" href="/staff"><h2>Staff</h2><p class="muted">Add your team and choose what each person can do.</p></a>
      {/if}
      {#if session.can("settings.manage")}
        <a class="card tile" href="/settings"><h2>Centre settings</h2><p class="muted">Name, address and what your bills and reports show.</p></a>
      {/if}
      {#if session.can("activity.view")}
        <a class="card tile" href="/activity"><h2>Activity log</h2><p class="muted">Who signed in and what changed.</p></a>
      {/if}
    </div>
  {/if}
</div>

<style>
  .grid { display: grid; gap: 14px; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); }
  .tile { padding: 18px; text-decoration: none; color: var(--text); display: grid; gap: 6px; }
  .tile:hover { border-color: var(--brand); }
  .tile p { margin: 0; }
</style>
