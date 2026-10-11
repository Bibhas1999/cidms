<script lang="ts">
  import Icon from "./Icon.svelte";

  // The summary shown after a failed submit, as in the Sandhata Registry: announced by screen readers,
  // focused, and each line links to its field. `labels` turns field names into the words on the form.
  let { form, labels = {}, idPrefix = "" }: {
    form: { errors: Record<string, string>; submitted: boolean; summary: (el: HTMLElement) => { destroy: () => void } };
    labels?: Record<string, string>; idPrefix?: string;
  } = $props();

  const list = $derived(Object.entries(form.errors));

  function go(e: MouseEvent, field: string) {
    e.preventDefault();
    const el = document.getElementById(idPrefix + field) ?? document.querySelector<HTMLElement>(`[name="${field}"]`);
    el?.focus();
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
  }
</script>

<div use:form.summary tabindex="-1" class="form-summary" class:is-shown={form.submitted && list.length > 0} role="alert" aria-live="assertive">
  {#if form.submitted && list.length}
    <div class="alert alert-destructive">
      <Icon name="alert" />
      <div>
        <div class="alert-title">{list.length === 1 ? "There's 1 thing to fix" : `There are ${list.length} things to fix`}</div>
        <ul class="error-list">
          {#each list as [field, message] (field)}
            <li><a href="#{idPrefix}{field}" onclick={(e) => go(e, field)}>{labels[field] ? `${labels[field]}: ` : ""}{message}</a></li>
          {/each}
        </ul>
      </div>
    </div>
  {/if}
</div>

<style>
  .form-summary { outline: none; }
  .form-summary:not(.is-shown) { display: contents; }
</style>
