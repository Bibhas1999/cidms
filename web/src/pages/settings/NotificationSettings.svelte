<script lang="ts">
  import { z } from "zod";
  import FormErrors from "../../components/FormErrors.svelte";
  import Icon from "../../components/Icon.svelte";
  import InfoTip from "../../components/InfoTip.svelte";
  import { get, post } from "../../lib/api";
  import { Form } from "../../lib/form.svelte";
  import { notifications, popupsSupported, showPopup, type KindPref, type Preferences } from "../../lib/notifications.svelte";
  import { notify, notifyError } from "../../lib/toast.svelte";

  // Which notifications you get, and whether this browser may show pop-ups for them. Saved for your account
  // (pop-up permission itself is per browser: each computer asks once).
  let {}: { embedded?: boolean } = $props();

  const schema = z.object({ browser_popups: z.boolean(), enabled: z.record(z.string(), z.boolean()) });
  let kinds = $state<KindPref[]>([]);
  let loading = $state(true);
  let permission = $state<NotificationPermission | "unsupported">(popupsSupported() ? Notification.permission : "unsupported");
  let saved = $state("");

  const form = new Form({
    schema, initial: { browser_popups: false, enabled: {} as Record<string, boolean> },
    onSubmit: async (v) => {
      const muted = kinds.filter((k) => k.can_mute && !v.enabled[k.code]).map((k) => k.code);
      const p = await notifications.savePreferences(muted, v.browser_popups);
      load(p);
      notify("Your notification settings are saved.");
    },
  });

  function load(p: Preferences) {
    kinds = p.kinds;
    const values = { browser_popups: p.browser_popups, enabled: Object.fromEntries(p.kinds.map((k) => [k.code, k.enabled])) };
    form.reset(values);
    saved = JSON.stringify(values);
  }

  $effect(() => {
    get<Preferences>("/api/notifications/preferences").then(load)
      .catch((e) => notifyError(e, { title: "Couldn't load your notification settings" }))
      .finally(() => (loading = false));
  });

  const dirty = $derived(!loading && JSON.stringify($state.snapshot(form.values)) !== saved);

  async function allowPopups() {
    if (!popupsSupported()) return;
    permission = await Notification.requestPermission();
    if (permission === "granted") {
      form.values.browser_popups = true;
      await showPopup("Pop-ups are on", "This is how CIDMS will tell you about things while you're in another tab.", "/notifications", "sdms-test");
      notify("Pop-ups are allowed. Save to keep them on.", { kind: "info" });
    } else if (permission === "denied") {
      notify("The browser blocked pop-ups. Allow them for this site in the browser's site settings (the lock icon next to the address).",
             { kind: "warning", duration: 0 });
    }
  }

  async function sendTest() {
    try {
      await post("/api/notifications/test");
      notify("A test notification is on its way to the bell.");
    } catch (e) {
      notifyError(e, { title: "Couldn't send a test notification" });
    }
  }

  async function testPopup() {
    if (!(await showPopup("Test pop-up", "Pop-ups are working in this browser.", "/notifications", "sdms-test")))
      notify("This browser didn't show the pop-up. Check that pop-ups are allowed for this site.", { kind: "warning" });
  }

  const labels = $derived(Object.fromEntries(kinds.map((k) => [`enabled.${k.code}`, k.label])));
</script>

<form class="card" onsubmit={(e) => form.submit(e).catch((err) => notifyError(err, { title: "Couldn't save your notification settings" }))} novalidate>
  <div class="card-header"><div><h2 class="card-title">Notifications</h2>
    <p class="card-description">What you hear about in the bell at the top of the page, and pop-ups when CIDMS is in another tab.</p></div></div>
  <div class="card-content stack-lg">
    <FormErrors {form} {labels} idPrefix="np_" />

    <fieldset class="group">
      <legend class="label row" style="gap: 6px">Browser pop-ups
        <InfoTip about="browser pop-ups" text="A small message from your computer, shown only while CIDMS is open in a tab you aren't looking at. Clicking it brings you to the right page. Nothing is shown when the tab is in front: the bell is enough then." /></legend>
      {#if permission === "unsupported"}
        <p class="text-sm text-muted">This browser can't show pop-ups. The bell still shows everything.</p>
      {:else}
        <label class="check-row">
          <input id="np_browser_popups" type="checkbox" class="checkbox" bind:checked={form.values.browser_popups} disabled={permission !== "granted"} {...form.field("browser_popups")} />
          <span><span class="font-semibold">Show pop-ups on this computer</span>
            <span class="hint" style="display:block">{permission === "granted" ? "Allowed in this browser." : permission === "denied" ? "Blocked in this browser's site settings." : "The browser will ask you first."}</span></span>
        </label>
        <div class="row-wrap">
          {#if permission !== "granted"}
            <button class="btn btn-outline" type="button" onclick={allowPopups} disabled={permission === "denied"}><Icon name="bell" /> Allow browser pop-ups</button>
          {:else}
            <button class="btn btn-outline" type="button" onclick={testPopup}><Icon name="bell" /> Show a test pop-up</button>
          {/if}
          <button class="btn btn-ghost" type="button" onclick={sendTest}>Send a test notification to the bell</button>
        </div>
      {/if}
    </fieldset>

    <fieldset class="group">
      <legend class="label">What to tell me about</legend>
      {#if loading}
        <p class="text-sm text-muted">Loading…</p>
      {:else}
        <ul class="kinds">
          {#each kinds as k (k.code)}
            <li class="kind">
              <label class="check-row grow" for="np_{k.code}">
                <input id="np_{k.code}" type="checkbox" class="checkbox" bind:checked={form.values.enabled[k.code]} disabled={!k.can_mute}
                       {...form.field(`enabled.${k.code}`)} />
                <span><span class="font-semibold">{k.label}</span>
                  <span class="hint" style="display:block">{k.audience}{k.can_mute ? "" : " · always on, for your account's safety"}</span></span>
              </label>
              <InfoTip about={k.label} text={`${k.description} Who gets it: ${k.audience.toLowerCase()}.${k.can_mute ? "" : " This one can't be turned off."}`} />
            </li>
          {/each}
        </ul>
      {/if}
    </fieldset>
  </div>
  <div class="card-footer">
    <button class="btn btn-outline" type="button" disabled={!dirty || form.submitting} onclick={() => load({ kinds, browser_popups: JSON.parse(saved).browser_popups })}>Discard</button>
    <button class="btn btn-primary" type="submit" disabled={!dirty || form.submitting}><Icon name="check" /> {form.submitting ? "Saving…" : "Save changes"}</button>
  </div>
</form>

<style src="./styles/NotificationSettings.css"></style>
