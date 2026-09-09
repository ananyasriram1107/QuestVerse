// Whether the player has explicitly switched on Offline Mode -- when true,
// api.js skips trying the real backend entirely and goes straight to the
// in-browser offline engine (see src/offline/), instead of waiting out a
// network timeout first.
const OFFLINE_KEY = "questverse_offline_mode_v1";

export function isOfflineMode() {
  try {
    return localStorage.getItem(OFFLINE_KEY) === "true";
  } catch {
    return false;
  }
}

export function setOfflineMode(enabled) {
  try {
    localStorage.setItem(OFFLINE_KEY, enabled ? "true" : "false");
  } catch {
    // localStorage unavailable -- the toggle just won't persist across reloads
  }
}
