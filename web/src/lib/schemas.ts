// Zod pieces shared by the forms (lib/form.svelte.ts), with the same rules and words the server uses.

import { z } from "zod";
import { ApiError } from "./api";
import { phoneProblem, splitPhone } from "./phone";
import { notifyError } from "./toast.svelte";

/** A mobile number as PhoneInput gives it ("+919876543210" or ""), checked for its country. */
export const phone = (required = false, missing = "Enter the mobile number.") =>
  z.string().superRefine((v, ctx) => {
    const { dial, number } = splitPhone(v);
    const problem = !number && required ? missing : phoneProblem(dial, number, required);
    if (problem) ctx.addIssue({ code: "custom", message: problem });
  });

/** Text that must be filled in (trimmed), with a maximum length. */
export const text = (message: string, max = 200, min = 1) =>
  z.string().trim().min(min, message).max(max, `Keep it under ${max} characters.`);

// Name rules, the same as the Sandhata Registry's (and app/schemas_billing.py on the server).
const LETTER = /\p{L}/gu;
const letters = (v: string) => (v.match(LETTER) || []).length;

/** People's names: letters, spaces, hyphens, apostrophes and full stops. */
export function personNameProblem(v: string, label: string): string {
  if (/[^\p{L}\p{M} '’.-]/u.test(v)) return `${label} can only contain letters, spaces, hyphens (-), apostrophes (') and full stops.`;
  if (!/^\p{L}/u.test(v)) return `${label} must start with a letter.`;
  if (/[-'’]$/.test(v)) return `${label} can't end with a hyphen or apostrophe.`;
  if (/[-'’.]{2,}/.test(v)) return `${label} can't have two symbols in a row.`;
  if (/ [-'’]|[-'’] /.test(v)) return `${label} can't have a space next to a hyphen or apostrophe.`;
  if (letters(v) < 2) return `${label} must have at least 2 letters.`;
  return "";
}

/** A referring doctor or hospital: words, numbers and a few joining symbols ("Dr. A. Sen (MD)", "Apollo 24/7"). */
export function titleProblem(v: string, label: string): string {
  if (/[^\p{L}\p{M}\p{N} \-–—&()/.,'’+:#]/u.test(v)) return `${label} can only contain letters, numbers, spaces and - & ( ) / . , ' + : #`;
  if (!/^[\p{L}\p{N}]/u.test(v)) return `${label} must start with a letter or number.`;
  if (!/[\p{L}\p{N})+#]$/u.test(v)) return `${label} must end with a letter, number or closing bracket.`;
  if (/([\-–—&/.,'’:])/.test(v)) return `${label} can't repeat the same symbol twice in a row.`;
  if (letters(v) < 2) return `${label} must have at least 2 letters.`;
  if ((v.match(/\(/g) || []).length !== (v.match(/\)/g) || []).length) return `${label} has an unmatched bracket.`;
  return "";
}

const named = (schema: z.ZodString, rule: (v: string, label: string) => string, label: string) =>
  schema.transform((v) => v.replace(/\s+/g, " ").normalize("NFC")).superRefine((v, ctx) => {
    const problem = v ? rule(v, label) : "";
    if (problem) ctx.addIssue({ code: "custom", message: problem });
  });

/** A person's name (patient, guardian). */
export const personName = (message: string, max = 200, min = 2, label = "The name") => named(text(message, max, min), personNameProblem, label);
export const optionalPersonName = (max = 200, label = "The name") => named(optionalText(max), personNameProblem, label);

/** A referring doctor or hospital. */
export const referrerName = (message: string, max = 200, min = 2) => named(text(message, max, min), titleProblem, "The name");

/** Optional text, trimmed. */
export const optionalText = (max = 200) => z.string().trim().max(max, `Keep it under ${max} characters.`);

/** An email that may be left empty. */
export const optionalEmail = z.string().trim().max(254).refine((v) => !v || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v), "Enter an email like name@example.com.");

export const email = (message = "Enter the email address.") =>
  z.string().trim().min(1, message).max(254).refine((v) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v), "Enter an email like name@example.com.");

/** A whole number from a number box (which gives a number, or null / "" when empty). */
export const wholeNumber = (opts: { min: number; max: number; required?: string; label?: string }) =>
  z.any().superRefine((v, ctx) => {
    if (v === null || v === undefined || v === "") {
      if (opts.required) ctx.addIssue({ code: "custom", message: opts.required });
      return;
    }
    const n = Number(v);
    if (!Number.isInteger(n) || n < opts.min || n > opts.max)
      ctx.addIssue({ code: "custom", message: `Enter ${opts.label ?? "a whole number"} from ${opts.min} to ${opts.max}.` });
  });

/** A money amount from a number box. */
export const money = (required = "Enter the amount.") =>
  z.any().superRefine((v, ctx) => {
    if (v === null || v === undefined || v === "") { ctx.addIssue({ code: "custom", message: required }); return; }
    const n = Number(v);
    if (!Number.isFinite(n) || n < 0) ctx.addIssue({ code: "custom", message: "Enter an amount of 0 or more." });
    else if (Math.round(n * 100) !== n * 100 && Math.abs(Math.round(n * 100) - n * 100) > 1e-6)
      ctx.addIssue({ code: "custom", message: "Use at most two decimal places (paise)." });
  });

/**
 * The submit handler for a <form> run by a Form: field errors from the server land beside the fields (the
 * Form does that); anything else becomes an error toast titled `title`.
 *   <form onsubmit={submitting(form, "Couldn't save")}>
 */
export function submitting(form: { submit: (e?: Event) => Promise<void> }, title: string) {
  return (e: Event) => {
    form.submit(e).catch((err) => {
      if (err instanceof ApiError && Object.keys(err.fieldErrors).length) return;
      notifyError(err, { title });
    });
  };
}
