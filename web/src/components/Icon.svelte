<script lang="ts">
  import { ICONS } from "../lib/icons";

  // A decorative icon from lib/icons.ts. Pair it with visible text (or an aria-label on the control).
  let { name, size = "", class: extra = "" }: { name: string; size?: "" | "sm"; class?: string } = $props();
</script>

<svg class="icon {size === 'sm' ? 'icon-sm' : ''} {extra}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
     stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">{@html ICONS[name] ?? ""}</svg>
