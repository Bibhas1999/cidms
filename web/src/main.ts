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
    navigator.serviceWorker.register("/sw.js")
      .then(() => navigator.serviceWorker.ready)
      .then((reg) => {
        // Keep every file this page loaded (scripts, styles, fonts), so the app opens without the internet.
        const files = performance.getEntriesByType("resource").map((e) => e.name)
          .filter((u) => u.startsWith(location.origin) && /\/(assets|icons)\//.test(u));
        reg.active?.postMessage({ type: "keep", files });
      })
      .catch((e) => console.warn("Service worker not registered", e));
  });
}
