import "./app.css";
import { mount } from "svelte";
import App from "./App.svelte";
import { installGlobalErrorHandlers } from "./lib/errors";
import { installRouter } from "./lib/router.svelte";
import { applyTheme, getTheme } from "./lib/theme";

applyTheme(getTheme());
installGlobalErrorHandlers();
installRouter();

export default mount(App, { target: document.getElementById("app")! });
