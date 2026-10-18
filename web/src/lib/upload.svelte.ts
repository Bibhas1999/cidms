// Resumable uploads: the file goes up in pieces (PUT /api/uploads/<id> with Content-Range), so progress is shown as it
// goes, it can be paused and resumed, and a dropped connection only costs the piece in flight. Before carrying on,
// the browser asks the server how much it already has. The upload's id is remembered for this file (name, size,
// date), so choosing the same file again after a reload carries on rather than starting over.
import { api, ApiError, csrfToken, get } from "./api";

export type UploadStatus = "idle" | "uploading" | "paused" | "done" | "error";

interface UploadInfo { id: string; filename: string; size: number; received: number; chunk_size: number; complete: boolean }

const RETRIES = 4;
const remembered = (f: File) => `upload:${f.name}:${f.size}:${f.lastModified}`;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export class ResumableUpload {
  status = $state<UploadStatus>("idle");
  sent = $state(0);
  total = $state(0);
  error = $state("");
  /** Bytes per second, smoothed: for "about N s left". */
  rate = $state(0);
  id = "";

  #file: File;
  #purpose: string;
  #xhr: XMLHttpRequest | null = null;
  #chunk = 256 * 1024;
  #run = 0; // bumps on pause/cancel, so an old loop stops quietly

  constructor(file: File, purpose: string) {
    this.#file = file;
    this.#purpose = purpose;
    this.total = file.size;
  }

  get percent(): number {
    return this.total ? Math.min(100, Math.floor((this.sent / this.total) * 100)) : 0;
  }

  get secondsLeft(): number | null {
    return this.rate > 0 && this.status === "uploading" ? Math.ceil((this.total - this.sent) / this.rate) : null;
  }

  /** Start, or carry on after a pause or an error. Resolves with the upload id once every byte is in. */
  async start(): Promise<string> {
    const run = ++this.#run;
    this.status = "uploading";
    this.error = "";
    try {
      await this.#open();
      let failures = 0;
      while (this.sent < this.total) {
        if (run !== this.#run) throw new DOMException("Paused", "AbortError");
        const start = this.sent;
        const end = Math.min(start + this.#chunk, this.total) - 1;
        try {
          const info = await this.#send(start, end);
          this.sent = info.received;
          failures = 0;
        } catch (e) {
          if ((e as Error).name === "AbortError") throw e;
          if (e instanceof ApiError && e.status === 409) { await this.#refresh(); continue; } // out of step: ask where it got to
          if (e instanceof ApiError && e.status !== 0 && e.status < 500) throw e;
          if (++failures > RETRIES) throw e;
          await sleep(1000 * 2 ** (failures - 1));
          await this.#refresh().catch(() => {});
        }
      }
      if (run !== this.#run) throw new DOMException("Paused", "AbortError");
      this.status = "done";
      this.#forget();
      return this.id;
    } catch (e) {
      if ((e as Error).name === "AbortError") {
        if (this.status === "uploading") this.status = "paused";
      } else {
        this.status = "error";
        this.error = e instanceof Error ? e.message : String(e);
      }
      throw e;
    }
  }

  pause(): void {
    if (this.status !== "uploading") return;
    this.#run++;
    this.status = "paused";
    this.#xhr?.abort();
  }

  /** Stop and throw away what the server has. */
  async cancel(): Promise<void> {
    this.#run++;
    this.#xhr?.abort();
    this.status = "idle";
    this.sent = 0;
    this.#forget();
    if (this.id) await api("DELETE", `/api/uploads/${this.id}`, { progress: false }).catch(() => {});
    this.id = "";
  }

  async #open(): Promise<void> {
    if (!this.id) {
      try { this.id = localStorage.getItem(remembered(this.#file)) ?? ""; } catch { /* storage blocked */ }
    }
    if (this.id) {
      try { await this.#refresh(); return; } catch { this.id = ""; } // expired: start again
    }
    const info = await api<UploadInfo>("POST", "/api/uploads",
                                       { body: { filename: this.#file.name, size: this.#file.size, purpose: this.#purpose }, progress: false });
    this.id = info.id;
    this.#chunk = info.chunk_size;
    this.sent = info.received;
    try { localStorage.setItem(remembered(this.#file), this.id); } catch { /* storage blocked */ }
  }

  async #refresh(): Promise<void> {
    const info = await get<UploadInfo>(`/api/uploads/${this.id}`);
    this.#chunk = info.chunk_size;
    this.sent = info.received;
  }

  #forget(): void {
    try { localStorage.removeItem(remembered(this.#file)); } catch { /* storage blocked */ }
  }

  /** One piece, by XMLHttpRequest so the bar moves while it's in flight (fetch can't report upload progress). */
  #send(start: number, end: number): Promise<UploadInfo> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      this.#xhr = xhr;
      const began = performance.now();
      xhr.open("PUT", `/api/uploads/${this.id}`);
      xhr.withCredentials = true;
      xhr.setRequestHeader("Content-Type", "application/octet-stream");
      xhr.setRequestHeader("Content-Range", `bytes ${start}-${end}/${this.total}`);
      xhr.setRequestHeader("X-CSRF-Token", csrfToken());
      xhr.upload.onprogress = (e) => { if (this.status === "uploading") this.sent = start + e.loaded; };
      xhr.onload = () => {
        this.#xhr = null;
        let body: any = null;
        try { body = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
        if (xhr.status >= 200 && xhr.status < 300) {
          const seconds = (performance.now() - began) / 1000;
          const now = (end - start + 1) / Math.max(seconds, 0.001);
          this.rate = this.rate ? this.rate * 0.7 + now * 0.3 : now;
          resolve(body as UploadInfo);
        } else {
          reject(new ApiError(xhr.status, body?.message ?? `The upload failed (${xhr.status}).`, body?.field ?? null, body?.detail ?? [], body?.request_id ?? null));
        }
      };
      xhr.onerror = () => { this.#xhr = null; reject(new ApiError(0, "The connection dropped. Resume to carry on from where it stopped.")); };
      xhr.onabort = () => { this.#xhr = null; reject(new DOMException("Paused", "AbortError")); };
      xhr.send(this.#file.slice(start, end + 1));
    });
  }
}
