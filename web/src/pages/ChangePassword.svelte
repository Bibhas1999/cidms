<script lang="ts">
  import PasswordInput from "../components/PasswordInput.svelte";
  import { z } from "zod";
  import Button from "../components/Button.svelte";
  import Field from "../components/Field.svelte";
  import FormErrors from "../components/FormErrors.svelte";
  import { post } from "../lib/api";
  import { Form } from "../lib/form.svelte";
  import { navigate } from "../lib/router.svelte";
  import { submitting } from "../lib/schemas";
  import { session } from "../lib/session.svelte";
  import { notify } from "../lib/toast.svelte";
  import type { Me } from "../lib/types";

  const forced = $derived(session.me?.must_change_password ?? false);

  const schema = z.object({
    current: z.string().min(1, "Enter your current password."),
    next: z.string().min(10, "Use at least 10 characters.").max(200, "Keep it under 200 characters.")
      .refine((v) => /[A-Za-z]/.test(v) && /[^A-Za-z]/.test(v), "Mix letters with numbers or symbols."),
    confirm: z.string().min(1, "Type the new password again."),
  });
  const labels = { current: "Current password", next: "New password", confirm: "New password again" };

  const form = new Form({
    schema, initial: { current: "", next: "", confirm: "" },
    rules: (v, add) => {
      if (v.confirm && v.next !== v.confirm) add("confirm", "The two new passwords don't match.");
      if (v.current && v.next && v.current === v.next) add("next", "Choose a password different from the current one.");
    },
    serverFields: { current_password: "current", new_password: "next" },
    onSubmit: async (v) => {
      session.setMe(await post<Me>("/api/auth/password", { current_password: v.current, new_password: v.next }));
      notify("Password changed. You've been signed out on your other devices.");
      navigate("/", { replace: true });
    },
  });
</script>

<div class="pw-wrap">
  <form class="card pw-card" onsubmit={submitting(form, "Couldn't change the password")} novalidate>
    <div class="card-header"><div>
      <span class="eyebrow">Your account</span>
      <h1 class="page-title pw-title">{forced ? "Choose your own password" : "Change password"}</h1>
      <p class="card-description">{forced ? "You signed in with a temporary password. Choose a new one to continue." : "You'll stay signed in here; other devices are signed out."}</p>
    </div></div>
    <div class="card-content stack">
      <FormErrors {form} {labels} />
      <Field id="current" label={forced ? "Temporary password" : "Current password"} required error={form.error("current")}>
        {#snippet children({ invalid, describedby })}
          <PasswordInput id="current" autocomplete="current-password" bind:value={form.values.current} {...form.field("current")}
                 aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
      <Field id="next" label="New password" required error={form.error("next")} hint="At least 10 characters, mixing letters with numbers or symbols."
             tip="A short sentence works well, e.g. three words and a number. Don't reuse a password from another site.">
        {#snippet children({ invalid, describedby })}
          <PasswordInput id="next" autocomplete="new-password" bind:value={form.values.next} {...form.field("next")}
                 aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
      <Field id="confirm" label="New password again" required error={form.error("confirm")}>
        {#snippet children({ invalid, describedby })}
          <PasswordInput id="confirm" autocomplete="new-password" bind:value={form.values.confirm} {...form.field("confirm")}
                 aria-invalid={invalid} aria-describedby={describedby} />
        {/snippet}
      </Field>
    </div>
    <div class="card-footer">
      {#if forced}<Button onclick={() => session.logout()}>Sign out</Button>
      {:else}<Button href="/">Cancel</Button>{/if}
      <Button variant="primary" type="submit" loading={form.submitting} loadingText="Saving…">Save password</Button>
    </div>
  </form>
</div>

<style>
  .pw-wrap { min-height: 70vh; display: grid; place-items: center; padding: 16px 0; }
  .pw-card { width: min(460px, 100%); }
  .pw-title { margin-top: 8px; }
</style>
