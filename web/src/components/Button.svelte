<script lang="ts">
  import type { Snippet } from "svelte";
  import { tooltip as tip } from "../lib/tooltip";
  import Icon from "./Icon.svelte";

  // The one button of the app. Renders a <button>, or an <a> when given `href`, with the same look:
  //   <Button variant="primary" icon="plus" href="/bills/new">New bill</Button>
  //   <Button variant="outline" loading={saving} loadingText="Saving…" type="submit" form="x">Save</Button>
  //   <Button variant="ghost" size="sm" tooltip="Print this bill" icon="printer">Print</Button>
  // variant  primary | outline | ghost | destructive | ghost-destructive | secondary   (default outline)
  // size     sm | md | lg  ·  block = full width  ·  mobileBlock = full width on phones only (page actions)
  // loading  locks the button and shows a spinner (no double submits). Other attributes pass through.
  type Variant = "primary" | "outline" | "ghost" | "destructive" | "ghost-destructive" | "secondary";
  let { variant = "outline", size = "md", loading = false, loadingText = "", icon = "", iconRight = "", href = "", newTab = false,
        block = false, mobileBlock = false, tooltip = "", disabled = false, type = "button", class: cls = "", children, ...rest }: {
    variant?: Variant; size?: "sm" | "md" | "lg"; loading?: boolean; loadingText?: string; icon?: string; iconRight?: string;
    href?: string; newTab?: boolean; block?: boolean; mobileBlock?: boolean; tooltip?: string; disabled?: boolean;
    type?: "button" | "submit" | "reset"; class?: string; children?: Snippet; [key: string]: any;
  } = $props();

  const classes = $derived(["btn", `btn-${variant}`, size !== "md" ? `btn-${size}` : "", block ? "btn-block" : "",
    mobileBlock ? "btn-mobile-block" : "", loading ? "is-loading" : "", !children ? "btn-icon" : "", cls].filter(Boolean).join(" "));
  const iconSize = $derived(size === "sm" ? "sm" : "");
</script>

{#snippet inner()}
  {#if loading}<span class="btn-spinner" aria-hidden="true"></span>{:else if icon}<Icon name={icon} size={iconSize} />{/if}
  {#if loading && loadingText}{loadingText}{:else if children}{@render children()}{/if}
  {#if iconRight && !loading}<Icon name={iconRight} size={iconSize} />{/if}
{/snippet}

{#if href && !disabled}
  <a class={classes} {href} target={newTab ? "_blank" : undefined} rel={newTab ? "noopener" : undefined} use:tip={tooltip} {...rest}>{@render inner()}</a>
{:else}
  <button class={classes} {type} disabled={disabled || loading} aria-busy={loading || undefined} use:tip={tooltip} {...rest}>{@render inner()}</button>
{/if}

<style src="./styles/Button.css"></style>
