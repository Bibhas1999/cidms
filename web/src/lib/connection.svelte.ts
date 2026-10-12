// Can we reach CIDMS right now? Two things can be down: this computer's connection (navigator.onLine), or the
// way to the server (the centre's internet is out but the Wi-Fi is up, or the server is restarting). A request
// that can't get through marks the server unreachable; then /healthz is tried every 10 seconds until it answers.

class Connection {
  online = $state(typeof navigator === "undefined" ? true : navigator.onLine);
  reachable = $state(true);
  #timer: ReturnType<typeof setInterval> | null = null;
  #listeners = new Set<() => void>();

  /** Bills can be saved to CIDMS now. */
  get usable(): boolean {
    return this.online && this.reachable;
  }

  /** Called when the connection comes back (to send offline bills). */
  onBack(fn: () => void): () => void {
    this.#listeners.add(fn);
    return () => this.#listeners.delete(fn);
  }

  markDown(): void {
    if (!this.reachable) return;
    this.reachable = false;
    this.#timer ??= setInterval(() => void this.check(), 10_000);
  }

  markUp(): void {
    if (this.#timer) { clearInterval(this.#timer); this.#timer = null; }
    const was = this.usable;
    this.reachable = true;
    if (!was && this.usable) this.#listeners.forEach((fn) => fn());
  }

  async check(): Promise<boolean> {
    if (!navigator.onLine) return false;
    try {
      const r = await fetch("/healthz", { cache: "no-store" });
      if (r.ok) { this.markUp(); return true; }
    } catch { /* still down */ }
    return false;
  }

  install(): void {
    window.addEventListener("online", () => {
      // The computer is back on a network; whether CIDMS answers is checked before anything is sent.
      this.online = true;
      this.reachable = false;
      this.#timer ??= setInterval(() => void this.check(), 10_000);
      void this.check();
    });
    window.addEventListener("offline", () => { this.online = false; });
  }
}

export const connection = new Connection();
