// The form engine, the same behaviour as the Sandhata Registry's (Final Form + Zod), for Svelte:
//
//   const form = new Form({ schema, initial, rules?, onSubmit })
//   <form onsubmit={form.submit}> … <input bind:value={form.values.name} {...form.field("name")} /> …
//   <Field error={form.error("name")}>  ·  <FormErrors {form} />
//
//   schema    Zod object: types, trimming, lengths, formats (the same rules the server checks)
//   rules     (values, add) => void for rules across fields (runs even when other fields are invalid)
//   onSubmit  async (data) => void, with data parsed by the schema. Throw an ApiError with field errors
//             (422/409) to show the server's messages next to the fields.
//
// When errors show (WCAG 2.2, Universal Design):
//  - not while someone is typing into a field for the first time; a field is checked when they leave it,
//    then on every change until it's fixed
//  - a failed submit shows every error at once, with a summary at the top that links to each field
//  - the submit button is locked while saving (no double submits); what was typed is never cleared

import type { z } from "zod";
import { ApiError } from "./api";

type Errors = Record<string, string>;
type AddError = (field: string, message: string) => void;

export interface FormOptions<S extends z.ZodType<any, any>> {
  schema: S;
  initial: z.input<S>;
  rules?: (values: z.input<S>, add: AddError) => void;
  onSubmit: (data: z.output<S>) => Promise<void> | void;
  /** Field names as the server calls them, when they differ ("patient.name" -> "name"). */
  serverFields?: Record<string, string>;
}

export class Form<S extends z.ZodType<any, any>> {
  values = $state() as z.input<S>;
  errors = $state<Errors>({});
  touched = $state<Record<string, boolean>>({});
  submitting = $state(false);
  submitted = $state(false);
  formError = $state("");
  #opts: FormOptions<S>;
  #summary: HTMLElement | null = null;

  constructor(opts: FormOptions<S>) {
    this.#opts = opts;
    this.values = structuredClone($state.snapshot(opts.initial) as z.input<S>);
  }

  /** Every current problem, by field (the first message per field). */
  check(): Errors {
    const out: Errors = {};
    const add: AddError = (f, m) => { if (!out[f]) out[f] = m; };
    const parsed = this.#opts.schema.safeParse($state.snapshot(this.values));
    if (!parsed.success) for (const issue of parsed.error.issues) add(issue.path.join(".") || "__all__", issue.message);
    this.#opts.rules?.($state.snapshot(this.values) as z.input<S>, add);
    return out;
  }

  /** Re-check, showing errors only for fields already left (or all after a submit attempt). */
  validate(): void {
    const all = this.check();
    const shown: Errors = {};
    for (const [f, m] of Object.entries(all)) if (this.submitted || this.touched[f]) shown[f] = m;
    this.errors = shown;
  }

  error(name: string): string {
    return this.errors[name] ?? "";
  }

  /** Spread on an input: checks it when left, then as it changes. */
  field(name: string) {
    return {
      name,
      onblur: () => { this.touched[name] = true; this.validate(); },
      oninput: () => { if (this.touched[name] || this.submitted) this.validate(); },
      onchange: () => { this.touched[name] = true; this.validate(); },
      "aria-invalid": !!this.errors[name],
    };
  }

  /** Where the error summary lives, so a failed submit can move focus to it. */
  summary = (el: HTMLElement) => {
    this.#summary = el;
    return { destroy: () => { this.#summary = null; } };
  };

  submit = async (e?: Event) => {
    e?.preventDefault();
    if (this.submitting) return;
    this.submitted = true;
    this.formError = "";
    this.validate();
    if (Object.keys(this.errors).length) {
      queueMicrotask(() => this.#summary?.focus());
      return;
    }
    const parsed = this.#opts.schema.safeParse($state.snapshot(this.values));
    this.submitting = true;
    try {
      await this.#opts.onSubmit(parsed.success ? parsed.data : (this.values as z.output<S>));
    } catch (err) {
      if (err instanceof ApiError && Object.keys(err.fieldErrors).length) {
        const map = this.#opts.serverFields ?? {};
        const mapped: Errors = {};
        for (const [f, m] of Object.entries(err.fieldErrors)) mapped[map[f] ?? f] = m;
        this.errors = mapped;
        queueMicrotask(() => this.#summary?.focus());
      }
      throw err;
    } finally {
      this.submitting = false;
    }
  };

  reset(values?: z.input<S>): void {
    this.values = structuredClone($state.snapshot(values ?? this.#opts.initial) as z.input<S>);
    this.errors = {};
    this.touched = {};
    this.submitted = false;
    this.formError = "";
  }
}
