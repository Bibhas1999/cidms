<script lang="ts">
  import Icon from "./Icon.svelte";
  import { tooltip } from "../lib/tooltip";

  // A password box with an eye button to show or hide what's typed, as on the sign-in page.
  //   <PasswordInput id="next" bind:value={form.values.next} autocomplete="new-password" {...form.field("next")}
  //                  aria-invalid={invalid} aria-describedby={describedby} />
  // Everything else (name, onblur, oninput, aria-*) goes straight onto the <input>.
  let { id, value = $bindable(""), autocomplete = "current-password", class: cls = "", ...rest }: {
    id: string; value?: string; autocomplete?: "current-password" | "new-password"; class?: string; [key: string]: unknown;
  } = $props();

  let show = $state(false);
  const word = $derived(show ? "Hide password" : "Show password");
</script>

<span class="pw">
  <input {id} class="input pw-input {cls}" type={show ? "text" : "password"} {autocomplete} bind:value spellcheck="false" {...rest} />
  <button type="button" class="pw-eye" aria-label={word} aria-pressed={show} aria-controls={id} use:tooltip={word}
          onclick={() => (show = !show)}>
    <Icon name={show ? "eyeOff" : "eye"} size="sm" />
  </button>
</span>

<style>
  .pw { position: relative; display: block; }
  .pw-input { padding-right: 42px; }
  .pw-eye { position: absolute; top: 50%; right: 4px; transform: translateY(-50%); display: grid; place-items: center; width: 32px; height: 30px;
    padding: 0; border: 0; border-radius: 6px; background: none; color: var(--muted-foreground); cursor: pointer; }
  .pw-eye:hover { color: var(--foreground); background: var(--muted); }
  .pw-eye:focus-visible { outline: none; box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 25%, transparent); }
</style>
