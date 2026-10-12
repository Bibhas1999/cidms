// "Install app": Supreme DMS is a PWA. Chrome, Edge and Android offer an install prompt, which the browser hands
// us as "beforeinstallprompt"; we keep it and show it when someone picks "Install app" in the profile menu.
// iPhones and iPads (Safari) have no prompt: there, people use Share → Add to Home Screen, so we tell them how.

interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

class Install {
  /** The browser's saved install prompt, when it offered one. */
  prompt = $state<InstallPromptEvent | null>(null);
  /** Already running as an installed app (or just installed). */
  installed = $state(false);

  readonly ios = typeof navigator !== "undefined" && /iphone|ipad|ipod/i.test(navigator.userAgent);

  /** Show "Install app": the browser can install it, or it's an iPhone/iPad not yet added to the home screen. */
  get available(): boolean {
    return !this.installed && (this.prompt !== null || this.ios);
  }

  start(): void {
    if (typeof window === "undefined") return;
    const standalone = window.matchMedia("(display-mode: standalone)").matches || (navigator as { standalone?: boolean }).standalone === true;
    this.installed = standalone;
    window.addEventListener("beforeinstallprompt", (e) => {
      e.preventDefault(); // keep it for our own button rather than the browser's mini bar
      this.prompt = e as InstallPromptEvent;
    });
    window.addEventListener("appinstalled", () => {
      this.installed = true;
      this.prompt = null;
    });
  }

  /** Ask the browser to install. Returns true when installed. */
  async run(): Promise<boolean> {
    const p = this.prompt;
    if (!p) return false;
    this.prompt = null; // a prompt can only be used once
    await p.prompt();
    const { outcome } = await p.userChoice;
    if (outcome === "accepted") this.installed = true;
    return outcome === "accepted";
  }
}

export const install = new Install();
