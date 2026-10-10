"use strict";
// The Appearance choice (Settings › Appearance), saved per browser. Loaded without defer, before the stylesheet, so the
// chosen theme applies before first paint. No choice, or storage blocked, follows the system (docs/ui.md "Design system").
const THEME_KEY = "home-manager-theme";
function storedTheme() {
  try { return localStorage.getItem(THEME_KEY) || "system"; } catch { return "system"; }
}
function applyTheme(value) {
  if (value === "light" || value === "dark") document.documentElement.dataset.theme = value;
  else delete document.documentElement.dataset.theme;
}
function setTheme(value) {
  try { if (value === "light" || value === "dark") localStorage.setItem(THEME_KEY, value); else localStorage.removeItem(THEME_KEY); } catch { /* Not saved; still applied. */ }
  applyTheme(value);
}
applyTheme(storedTheme());
