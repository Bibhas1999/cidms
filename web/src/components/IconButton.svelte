<script lang="ts">
  import { tooltip as tip } from "../lib/tooltip";
  import Icon from "./Icon.svelte";

  // A square button with only an icon. `label` is both its accessible name and its tooltip, so an icon is
  // never left unexplained:  <IconButton icon="printer" label="Print bill" href="/bills/1/print" newTab />
  // variant ghost (default) | outline | ghost-destructive · size sm | md. On touch screens it grows to 40px.
  let { icon, label, variant = "ghost", size = "md", href = "", newTab = false, disabled = false, tooltip = true, class: cls = "", onclick, ...rest }: {
    icon: string; label: string; variant?: "ghost" | "outline" | "ghost-destructive" | "primary"; size?: "sm" | "md";
    href?: string; newTab?: boolean; disabled?: boolean; tooltip?: boolean; class?: string; onclick?: (e: MouseEvent) => void; [key: string]: any;
  } = $props();

  const classes = $derived(`btn btn-${variant} btn-icon icon-button-sq ${size === "sm" ? "btn-sm" : ""} ${cls}`);
</script>

{#if href && !disabled}
  <a class={classes} {href} aria-label={label} target={newTab ? "_blank" : undefined} rel={newTab ? "noopener" : undefined}
     use:tip={tooltip ? label : ""} {onclick} {...rest}><Icon name={icon} size={size === "sm" ? "sm" : ""} /></a>
{:else}
  <button class={classes} type="button" aria-label={label} {disabled} use:tip={tooltip ? label : ""} {onclick} {...rest}>
    <Icon name={icon} size={size === "sm" ? "sm" : ""} /></button>
{/if}
