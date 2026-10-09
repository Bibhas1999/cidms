// Infinite scrolling over the server's paged lists (?page=&size= → {items, total, page, size}).
// A page keeps one InfiniteList, calls reset() from an $effect that reads its filters (so any filter change
// starts again from page 1), and puts <LoadMore> after its table to fetch the next page as the person scrolls.
// Every reset starts a new "generation": answers from an older generation are dropped, so rows from two
// different filters never mix.

import { untrack } from "svelte";

export type PageLike<T> = { items: T[]; total: number };

export class InfiniteList<T, R extends PageLike<T> = PageLike<T>> {
  /** Rows loaded so far, in server order. */
  items = $state.raw<T[]>([]);
  /** Rows the server has for the current filters. */
  total = $state(0);
  loading = $state(false);
  error = $state("");
  /** The first page's whole answer, for extras such as BillPage.sums; null until it arrives. */
  first = $state.raw<R | null>(null);
  #short = $state(false); // the server gave a short page: nothing more to ask for, whatever total says
  /** No more pages to fetch (false until the first page has arrived). */
  done = $derived(this.first !== null && (this.items.length >= this.total || this.#short));

  readonly size: number;
  #fetch: (page: number, size: number, signal: AbortSignal) => Promise<R>;
  #key: (item: T) => unknown;
  #page = 0;
  #gen = 0;
  #ctrl: AbortController | null = null;

  constructor(fetchPage: (page: number, size: number, signal: AbortSignal) => Promise<R>, size = 25,
              key: (item: T) => unknown = (item) => (item as { id?: unknown }).id) {
    this.#fetch = fetchPage;
    this.size = size;
    this.#key = key;
  }

  /** Abort anything in flight, forget the rows, and load page 1. With keep, the old rows stay shown until page 1 arrives
   *  (for refreshing after a change, so the table doesn't blink). */
  reset({ keep = false }: { keep?: boolean } = {}): void {
    this.abort();
    this.#page = 0;
    this.error = "";
    this.#short = false;
    if (!keep) {
      this.items = [];
      this.total = 0;
      this.first = null;
    }
    untrack(() => this.#load());
  }

  /** Load the next page, unless one is already loading or everything is here. Also retries after an error. */
  more(): void {
    if (this.loading || this.done) return;
    this.#load();
  }

  /** Stop whatever is in flight (on leaving the page). */
  abort(): void {
    this.#ctrl?.abort();
    this.#ctrl = null;
    this.#gen += 1;
    this.loading = false;
  }

  async #load(): Promise<void> {
    const gen = this.#gen;
    const ctrl = (this.#ctrl = new AbortController());
    const page = this.#page + 1;
    this.loading = true;
    this.error = "";
    try {
      const r = await this.#fetch(page, this.size, ctrl.signal);
      if (gen !== this.#gen) return;
      if (page === 1) {
        this.items = r.items;
        this.first = r;
      } else {
        // Rows can shift between pages when something is added meanwhile; don't show one twice.
        const seen = new Set(this.items.map(this.#key).filter((k) => k !== undefined));
        this.items = [...this.items, ...r.items.filter((i) => { const k = this.#key(i); return k === undefined || !seen.has(k); })];
      }
      this.total = r.total;
      this.#short = r.items.length < this.size;
      this.#page = page;
    } catch (e) {
      if (gen !== this.#gen || (e as Error)?.name === "AbortError") return;
      this.error = e instanceof Error ? e.message : String(e);
    } finally {
      if (gen === this.#gen) {
        this.loading = false;
        this.#ctrl = null;
      }
    }
  }
}
