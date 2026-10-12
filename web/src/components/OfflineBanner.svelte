<script lang="ts">
  import { connection } from "../lib/connection.svelte";
  import { offline } from "../lib/offline.svelte";
  import { session } from "../lib/session.svelte";

  // A strip across the top when CIDMS can't be reached (this computer is offline, or the centre's internet is
  // down): billing carries on, kept on this computer (lib/offline). Also says when offline bills are waiting
  // to go, are being sent, or need a look; and "Back online" for a moment when the connection returns.
  let back = $state(false);
  let wasUsable = connection.usable;
  let timer: ReturnType<typeof setTimeout>;
  $effect(() => {
    const now = connection.usable;
    if (now && !wasUsable) { back = true; clearTimeout(timer); timer = setTimeout(() => (back = false), 4000); }
    if (!now) back = false;
    wasUsable = now;
  });
  $effect(() => () => clearTimeout(timer));

  const canBill = $derived(!!session.me && !session.isPlatform && session.can("billing.create"));
  const waiting = $derived(offline.waiting);
  const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
</script>

{#if !connection.usable}
  <div class="offline-banner" role="status" aria-live="polite">
    {#if canBill}You're offline. You can still make bills: they're kept on this computer and sent when the connection is back.
    {:else}You're offline. Changes can't be saved until the connection is back.{/if}
    {#if canBill && waiting}<a href="/bills/offline">{plural(waiting, "bill", "bills")} waiting</a>{/if}
  </div>
{:else if canBill && offline.sending}
  <div class="offline-banner is-sending" role="status" aria-live="polite">Sending offline bills to CIDMS…</div>
{:else if canBill && offline.attention}
  <div class="offline-banner is-attention" role="status" aria-live="polite">
    {plural(offline.attention, "offline bill needs", "offline bills need")} a look before {offline.attention === 1 ? "it" : "they"} can be sent.
    <a href="/bills/offline">Open offline bills</a>
  </div>
{:else if canBill && waiting}
  <div class="offline-banner is-sending" role="status" aria-live="polite">{plural(waiting, "offline bill is", "offline bills are")} waiting to be sent. <a href="/bills/offline">Show</a></div>
{:else if back}
  <div class="offline-banner is-back" role="status" aria-live="polite">Back online.</div>
{/if}

<style>
  .offline-banner a { color: inherit; text-decoration: underline; margin-left: 8px; }
  .is-back { background: var(--success, #15803d); }
  .is-sending { background: var(--brand-navy, #1e3a8a); }
  .is-attention { background: #9a3412; }
</style>
