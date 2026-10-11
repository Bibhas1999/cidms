<script lang="ts">
  import { tooltip } from "../lib/tooltip";

  // A small rich-text box for report findings: bold, italic, underline, headings, lists. It edits HTML; the
  // server cleans it to the same small set of tags before saving, so what's shown here is what gets printed.
  let { id, value = $bindable(""), label, disabled = false, invalid = false, describedby, minHeight = 160, onblur, oninput }: {
    id: string; value?: string; label: string; disabled?: boolean; invalid?: boolean; describedby?: string;
    minHeight?: number; onblur?: () => void; oninput?: () => void;
  } = $props();

  let box: HTMLDivElement;

  // Follow changes from outside (a template applied, a version restored) without fighting the caret.
  $effect(() => {
    if (box && box.innerHTML !== value && document.activeElement !== box) box.innerHTML = value ?? "";
  });

  function run(command: string, arg?: string) {
    if (disabled) return;
    box.focus();
    document.execCommand(command, false, arg);
    changed();
  }

  function changed() {
    value = box.innerHTML;
    oninput?.();
  }

  function paste(e: ClipboardEvent) {
    // Paste words, not someone else's styling: plain text, line breaks kept as paragraphs.
    e.preventDefault();
    const text = e.clipboardData?.getData("text/plain") ?? "";
    const html = text.split(/\r?\n/).map((l) => l.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"))
      .map((l) => `<p>${l || "<br>"}</p>`).join("");
    document.execCommand("insertHTML", false, html);
    changed();
  }

  const TOOLS: { cmd: string; arg?: string; label: string; text: string; cls?: string }[] = [
    { cmd: "bold", label: "Bold (Ctrl+B)", text: "B", cls: "b" },
    { cmd: "italic", label: "Italic (Ctrl+I)", text: "I", cls: "i" },
    { cmd: "underline", label: "Underline (Ctrl+U)", text: "U", cls: "u" },
    { cmd: "formatBlock", arg: "H3", label: "Heading", text: "H" },
    { cmd: "formatBlock", arg: "P", label: "Normal text", text: "¶" },
    { cmd: "insertUnorderedList", label: "Bulleted list", text: "•" },
    { cmd: "insertOrderedList", label: "Numbered list", text: "1." },
    { cmd: "removeFormat", label: "Clear formatting", text: "⌫" },
  ];
</script>

<div class="rte" class:is-disabled={disabled} class:is-invalid={invalid}>
  {#if !disabled}
    <div class="rte-bar" role="toolbar" aria-label="{label} formatting" aria-controls={id}>
      {#each TOOLS as t (t.label)}
        <button type="button" class="rte-btn {t.cls ?? ''}" aria-label={t.label} use:tooltip={t.label}
                onmousedown={(e) => e.preventDefault()} onclick={() => run(t.cmd, t.arg)}>{t.text}</button>
      {/each}
    </div>
  {/if}
  <div bind:this={box} {id} class="rte-body" role="textbox" tabindex="0" aria-multiline="true" aria-label={label}
       aria-invalid={invalid} aria-describedby={describedby} aria-readonly={disabled}
       contenteditable={disabled ? "false" : "true"} style="min-height: {minHeight}px"
       oninput={changed} onblur={() => onblur?.()} onpaste={paste}></div>
</div>

<style>
  .rte { border: 1px solid var(--input, var(--border)); border-radius: 8px; background: var(--background); overflow: hidden; }
  .rte:focus-within { outline: 2px solid var(--ring, var(--primary)); outline-offset: 1px; }
  .rte.is-invalid { border-color: var(--destructive); }
  .rte.is-disabled { background: var(--muted); }
  .rte-bar { display: flex; flex-wrap: wrap; gap: 2px; padding: 4px; border-bottom: 1px solid var(--border); background: var(--muted); }
  .rte-btn { min-width: 30px; height: 28px; padding: 0 6px; border: 0; border-radius: 6px; background: none; color: var(--foreground);
    font: 600 13px var(--font-sans); cursor: pointer; }
  .rte-btn:hover, .rte-btn:focus-visible { background: var(--background); }
  .rte-btn.i { font-style: italic; }
  .rte-btn.u { text-decoration: underline; }
  .rte-body { padding: 10px 12px; font-size: 14px; line-height: 1.55; outline: none; overflow-wrap: anywhere; }
  .rte-body :global(p) { margin: 0 0 6px; }
  .rte-body :global(h2), .rte-body :global(h3), .rte-body :global(h4) { font-size: 15px; margin: 8px 0 4px; }
  .rte-body :global(ul), .rte-body :global(ol) { margin: 0 0 6px; padding-left: 22px; }
</style>
