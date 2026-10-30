<script lang="ts">
  import type { Snippet } from "svelte";

  // A file picker that's also a drag-and-drop target: wraps a clickable trigger (its children) in a native
  // <label> around a hidden file input, so clicking or dropping both work the same way. The caller still owns
  // the upload itself (its endpoint, its validation, its progress) - this only gets files out of the browser.
  //
  //   <FileDrop accept="image/png,image/jpeg" onfiles={(files) => upload(files[0])}>
  //     <Icon name="upload" /> Add DICOM files (.dcm) or a .zip
  //     <span class="hint">Drop them here or choose.</span>
  //   </FileDrop>                                                     (variant="zone", the default: a dashed box)
  //
  //   <FileDrop variant="button" onfiles={(files) => upload(files[0])}>
  //     <span class="btn btn-outline"><Icon name="user" size="sm" /> Change picture</span>
  //   </FileDrop>                                    ("button": no framing of its own - children keep their look)
  let { accept, multiple = false, disabled = false, variant = "zone", onfiles, children }: {
    accept?: string; multiple?: boolean; disabled?: boolean;
    /** "zone": a dashed drop box (this component's own look). "button": no framing - wrap an existing
        button/label and it keeps its look, dragging onto it still works. */
    variant?: "zone" | "button";
    onfiles: (files: File[]) => void;
    children: Snippet;
  } = $props();

  let input = $state<HTMLInputElement>();
  let over = $state(false);

  function take(list: FileList | null | undefined) {
    if (!list || !list.length || disabled) return;
    onfiles(multiple ? Array.from(list) : [list[0]]);
  }
</script>

<label class="file-drop file-drop-{variant}" class:is-over={over} class:is-disabled={disabled}
       ondragover={(e) => { e.preventDefault(); if (!disabled) over = true; }}
       ondragleave={() => (over = false)}
       ondrop={(e) => { e.preventDefault(); over = false; take(e.dataTransfer?.files); }}>
  {@render children()}
  <input bind:this={input} type="file" class="sr-only" {accept} {multiple} {disabled}
         onchange={(e) => { take(e.currentTarget.files); e.currentTarget.value = ""; }} />
</label>

<style src="./styles/FileDrop.css"></style>
