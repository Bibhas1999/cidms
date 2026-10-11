<script lang="ts">
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

  // Follow changes made from outside (a patient picked from the list, a form reset).
  $effect(() => {
    const parts = splitPhone(value);
    if (joinPhone(parts.dial, parts.number) !== joinPhone(dial, number)) { dial = parts.dial; number = parts.number; }
  });

  function push() {
    value = joinPhone(dial, number);
    oninput?.();
  }
</script>

<div class="phone" class:is-invalid={invalid}>
  <label class="sr-only" for="{id}-cc">Country code</label>
  <select id="{id}-cc" class="select cc" bind:value={dial} {disabled} onchange={push} onblur={onblur} aria-invalid={invalid}>
    {#each COUNTRIES as c (c.code)}<option value={c.dial}>{flag(c.code)} {c.dial}</option>{/each}
  </select>
  <input {id} class="input num tabular" type="tel" inputmode="numeric" autocomplete="tel-national" maxlength="14" {disabled}
         placeholder={dial === "+91" ? "98765 43210" : "Mobile number"} bind:value={number} aria-invalid={invalid} aria-describedby={describedby}
         oninput={() => { number = number.replace(/[^\d\s]/g, ""); push(); }} {onblur} />
</div>

<style>
  .phone { display: grid; grid-template-columns: 112px minmax(0, 1fr); }
  .cc { border-top-right-radius: 0; border-bottom-right-radius: 0; border-right-width: 0; padding-right: 26px; background-position: right 8px center; }
  .num { border-top-left-radius: 0; border-bottom-left-radius: 0; }
  .phone .cc:focus, .phone .num:focus { position: relative; z-index: 1; }
</style>
