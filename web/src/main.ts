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
import { installGlobalErrorHandlers } from "./lib/errors";
import { installRouter } from "./lib/router.svelte";
import { install } from "./lib/install.svelte";
import { applyTheme, getTheme } from "./lib/theme";

applyTheme(getTheme());
installGlobalErrorHandlers();
installRouter();
install.start();

export default mount(App, { target: document.getElementById("app")! });

// Installable app (PWA). Only the built app registers the worker: in development Vite serves fresh files.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((e) => console.warn("Service worker not registered", e));
  });
}
