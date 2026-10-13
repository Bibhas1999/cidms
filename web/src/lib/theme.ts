// Light, dark, or follow the system. Light until someone chooses otherwise; remembered on this device only.

export type Theme = "system" | "light" | "dark";
const KEY = "sdms.theme";
export const DEFAULT_THEME: Theme = "light";

export function getTheme(): Theme {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" || v === "system" ? v : DEFAULT_THEME;
  } catch {
    return DEFAULT_THEME;
  }
}

export function applyTheme(theme: Theme): void {
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* private window: the choice lasts until the page closes */
  }
}
