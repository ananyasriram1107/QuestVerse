import { useEffect } from "react";

const REVEAL_DURATION_MS = 1800;

// Full-screen badge callout shown right after claiming an achievement --
// zooms in, holds, then zooms back out and calls onDone so the caller can
// clear it. Purely decorative (pointer-events: none via CSS) so it never
// blocks interaction with the page underneath.
export default function BadgeUnlockReveal({ achievement, onDone }) {
  useEffect(() => {
    if (!achievement) {
      return undefined;
    }

    const timerId = setTimeout(onDone, REVEAL_DURATION_MS);
    return () => clearTimeout(timerId);
  }, [achievement, onDone]);

  if (!achievement) {
    return null;
  }

  return (
    <div className="badge-reveal" role="status" aria-live="assertive">
      <div className="badge-reveal__card">
        <span className="badge-reveal__title">Achievement Unlocked!</span>
        <span className="badge-reveal__icon" aria-hidden="true">{achievement.icon}</span>
        <strong className="badge-reveal__label">{achievement.label}</strong>
      </div>
    </div>
  );
}
