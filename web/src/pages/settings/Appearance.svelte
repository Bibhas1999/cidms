<script lang="ts">
  import Icon from "../../components/Icon.svelte";
  import { applyTheme, getTheme, type Theme } from "../../lib/theme";

  let theme = $state<Theme>(getTheme());
  const OPTIONS: [Theme, string, string, string][] = [
    ["light", "Light", "sun", "Dark text on a light page."],
    ["dark", "Dark", "moon", "Light text on a dark page: easier on the eyes at night."],
    ["system", "Match this computer", "monitor", "Follows the computer's own light or dark setting."],
  ];
</script>

<section class="card">
  <div class="card-header"><div><h2 class="card-title">Appearance</h2>
    <p class="card-description">Remembered on this computer only.</p></div></div>
  <div class="card-content">
    <div class="grid-3" role="radiogroup" aria-label="Theme">
      {#each OPTIONS as [value, label, icon, text] (value)}
        <label class="choice" class:is-on={theme === value}>
          <input class="sr-only" type="radio" name="theme" {value} checked={theme === value} onchange={() => { theme = value; applyTheme(value); }} />
          <span class="row" style="gap: 10px"><Icon name={icon} /><span class="font-semibold">{label}</span>{#if theme === value}<span style="margin-left:auto"><Icon name="check" /></span>{/if}</span>
          <span class="text-sm text-muted">{text}</span>
        </label>
      {/each}
    </div>
  </div>
</section>

<style src="./styles/Appearance.css"></style>
