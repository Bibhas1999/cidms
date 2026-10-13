<script lang="ts">
  import ClientBackupsPanel from "../../components/ClientBackupsPanel.svelte";

  // Settings > Backups for a centre's owner: the centre's own copies, downloads and restore.
  let {}: { embedded?: boolean } = $props();
</script>

<ClientBackupsPanel base="/api/backups" />
