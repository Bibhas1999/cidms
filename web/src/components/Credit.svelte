<script lang="ts">
  import Icon from "./Icon.svelte";
  // "Crafted with ♥ by Bibhas": where "Powered by" used to be (sidebar foot, sign-in panel).
  // `inherit` takes the surrounding text colour (on the coloured sign-in panel).
  let { class: cls = "", inherit = false }: { class?: string; inherit?: boolean } = $props();
</script>

<span class="credit {cls}" class:is-inherit={inherit}>
  Crafted with
  <Icon name="heart" class="heart" size={13} label="love" />
  by Bibhas
</span>

<style src="./styles/Credit.css"></style>
