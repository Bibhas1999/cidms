<script lang="ts">
  import { ICONS } from "../lib/icons";

  // The one way to draw an icon or small picture (every SVG body lives in lib/icons.ts):
  //   <Icon name="mail" />                        decorative, 18px, next to visible text
  //   <Icon name="lock" size="sm" />              15px
  //   <Icon name="svcCt" size={30} />             any size in px
  //   <Icon name="heart" label="love" />          meaningful on its own: announced to screen readers
  // Colour follows the text colour (currentColor); stroke width and anything else can be set in CSS.
  let { name, size = "", label = "", strokeWidth = 2, class: extra = "", ...rest }: {
    name: string; size?: "" | "sm" | number; label?: string; strokeWidth?: number; class?: string; [key: string]: unknown;
  } = $props();

  const def = $derived.by(() => {
    const d = ICONS[name];
    return typeof d === "string" ? { body: d } : d ?? { body: "" };
  });
  const px = $derived(typeof size === "number" ? `width: ${size}px; height: ${size}px;` : undefined);
</script>

<svg class="icon {size === 'sm' ? 'icon-sm' : ''} {extra}" style={px} viewBox={def.viewBox ?? "0 0 24 24"}
     fill={def.filled ? "currentColor" : "none"} stroke={def.filled ? "none" : "currentColor"} stroke-width={strokeWidth}
     stroke-linecap="round" stroke-linejoin="round" focusable="false"
     role={label ? "img" : undefined} aria-label={label || undefined} aria-hidden={label ? undefined : "true"} {...rest}>{@html def.body}</svg>
