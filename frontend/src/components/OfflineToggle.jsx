import { useState } from "react";
import { isOfflineMode, setOfflineMode } from "../utils/offlineMode";

export default function OfflineToggle() {
  const [offline, setOffline] = useState(() => isOfflineMode());

  function handleToggle() {
    const next = !offline;
    setOfflineMode(next);
    setOffline(next);
  }

  return (
    <button
      type="button"
      className={offline ? "offline-toggle offline-toggle--on" : "offline-toggle"}
      onClick={handleToggle}
      aria-pressed={offline}
      title={offline ? "Offline Mode is on -- using the built-in question bank, no server needed" : "Offline Mode is off -- using the live server"}
    >
      <span className="offline-toggle__track" aria-hidden="true">
        <span className="offline-toggle__thumb" />
      </span>
      <span className="offline-toggle__label">{offline ? "Offline" : "Online"}</span>
    </button>
  );
}
