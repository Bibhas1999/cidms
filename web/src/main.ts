// Fonts are self-hosted so the strict Content-Security-Policy (font-src 'self') holds: Inter for text,
// Montserrat for headings, as in the Sandhata Registry.
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/montserrat/600.css";
import "@fontsource/montserrat/700.css";
import "./styles/globals.css";
import "./styles/supreme.css";
import { mount } from "svelte";
import App from "./App.svelte";
import { installGlobalErrorHandlers } from "./lib/errors";
import { installRouter } from "./lib/router.svelte";
import { applyTheme, getTheme } from "./lib/theme";

applyTheme(getTheme());
installGlobalErrorHandlers();
installRouter();

export default mount(App, { target: document.getElementById("app")! });
