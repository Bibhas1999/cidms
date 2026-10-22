<script lang="ts">
  import { untrack } from "svelte";
  import { COUNTRIES, flag, joinPhone, splitPhone } from "../lib/phone";

  // A mobile number as two inputs: the country code and the number. `value` is the international form
  // ("+919876543210"), or "" when empty. Only digits can be typed; the number is checked by the form.
  let { id, value = $bindable(""), invalid = false, describedby, disabled = false, onblur, oninput }: {
    id: string; value?: string; invalid?: boolean; describedby?: string; disabled?: boolean;
    onblur?: () => void; oninput?: () => void;
  } = $props();

  const start = splitPhone(value);
  let dial = $state(start.dial);
  let number = $state(start.number);

  // Follow changes made from outside (a patient picked from the list, a form reset). Only `value` is watched:
  // watching the typed digits too made this undo each keystroke before it reached `value`.
  let last = value;
  $effect(() => {
    const v = value;
    untrack(() => {
      if (v === last) return;
      last = v;
      const parts = splitPhone(v);
      dial = parts.dial;
      number = parts.number;
    });
  });

  function push() {
    value = last = joinPhone(dial, number);
    oninput?.();
  }

  function typed(e: Event & { currentTarget: HTMLInputElement }) {
    const clean = e.currentTarget.value.replace(/[^\d\s]/g, "");
    if (clean !== e.currentTarget.value) e.currentTarget.value = clean;
    number = clean;
    push();
  }
</script>

<div class="phone" class:is-invalid={invalid}>
  <label class="sr-only" for="{id}-cc">Country code</label>
  <select id="{id}-cc" class="select cc" bind:value={dial} {disabled} onchange={push} onblur={onblur} aria-invalid={invalid}>
    {#each COUNTRIES as c (c.code)}<option value={c.dial}>{flag(c.code)} {c.dial}</option>{/each}
  </select>
  <input {id} class="input num tabular" type="tel" inputmode="numeric" autocomplete="tel-national" maxlength="14" {disabled}
         placeholder={dial === "+91" ? "98765 43210" : "Mobile number"} value={number} aria-invalid={invalid} aria-describedby={describedby}
         oninput={typed} {onblur} />
</div>

<style>
  .phone { display: grid; grid-template-columns: 96px minmax(0, 1fr); }
  .cc { border-top-right-radius: 0; border-bottom-right-radius: 0; border-right-width: 0; padding-left: 10px; padding-right: 24px; background-position: right 6px center; }
  .num { border-top-left-radius: 0; border-bottom-left-radius: 0; }
  .phone .cc:focus, .phone .num:focus { position: relative; z-index: 1; }
</style>
