import { sveltePreprocess } from "svelte-preprocess";

// Resolves each component's <style src="./X.css">; scoping still applies since the compiler sees the
// loaded content as if it were written inline.
export default { preprocess: sveltePreprocess() };
