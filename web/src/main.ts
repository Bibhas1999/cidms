// Fonts are self-hosted so the strict Content-Security-Policy (font-src 'self') holds: Inter everywhere.
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "./styles/globals.css";
import "./styles/supreme.css";
import "./styles/theme.css";
import "./charts.css";
import "./styles/mobile.css";
import { mount } from "svelte";
import App from "./App.svelte";
import { connection } from "./lib/connection.svelte";
import { pruneDrafts } from "./lib/drafts.svelte";
import { installGlobalErrorHandlers } from "./lib/errors";
import { installOffline } from "./lib/offline.svelte";
import { installRouter } from "./lib/router.svelte";
import { install } from "./lib/install.svelte";
import { applyTheme, getTheme } from "./lib/theme";
import { notify } from "./lib/toast.svelte";

applyTheme(getTheme());
installGlobalErrorHandlers();
installRouter();
pruneDrafts();
connection.install();
installOffline();
install.start();

export default mount(App, { target: document.getElementById("app")! });

// Installable app (PWA). Only the built app registers the worker: in development Vite serves fresh files.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    // Already controlled before this registration resolves: a returning visit, not the very first ever.
    // Only then does a later controllerchange mean a new version took over while the tab was open.
    let controlled = !!navigator.serviceWorker.controller;
    navigator.serviceWorker.register("/sw.js")
      .then(() => navigator.serviceWorker.ready)
      .then((reg) => {
        // Keep every file this page loaded (scripts, styles, fonts), so the app opens without the internet.
        const files = performance.getEntriesByType("resource").map((e) => e.name)
          .filter((u) => u.startsWith(location.origin) && /\/(assets|icons)\//.test(u));
        reg.active?.postMessage({ type: "keep", files });

        // A desk tab is often left open all day with no full page navigation, so the browser's own update
        // check (tied to navigation) may never run. Ask for one hourly, and whenever the tab regains focus.
        const checkForUpdate = () => reg.update().catch(() => {});
        setInterval(checkForUpdate, 60 * 60 * 1000);
        document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") checkForUpdate(); });
      })
      .catch((e) => console.warn("Service worker not registered", e));

    // The service worker skips waiting and claims every tab as soon as it activates, so this fires the
    // moment a newly deployed version takes over — only a reload actually loads its new files, so ask.
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (controlled) {
        notify("A new version of CIDMS is ready.", { kind: "info", duration: 0,
          action: { label: "Refresh", run: () => location.reload() } });
      }
      controlled = true;
    });
  });
}
