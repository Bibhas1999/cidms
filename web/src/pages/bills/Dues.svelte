<script lang="ts">
  import Bills from "./Bills.svelte";

  // Dues: the bills list, showing only bills with money still owed.
  let { params }: { params?: Record<string, string> } = $props();
</script>

<Bills mode="dues" {params} />
