import { useEffect, useState } from "react";
import { ACHIEVEMENTS } from "../achievements";
import { loadStats, loadUnlockedAchievements, unlockAchievement } from "../utils/achievementStore";
import BadgeUnlockReveal from "./BadgeUnlockReveal";

export default function AchievementsPage({ onClose }) {
  const [stats] = useState(() => loadStats());
  const [unlockedIds, setUnlockedIds] = useState(() => loadUnlockedAchievements());
  const [revealing, setRevealing] = useState(null);

  const locked = ACHIEVEMENTS.filter((achievement) => !unlockedIds.includes(achievement.id));
  const unlocked = ACHIEVEMENTS.filter((achievement) => unlockedIds.includes(achievement.id));

  function handleUnlock(achievement) {
    setUnlockedIds(unlockAchievement(achievement.id));
    setRevealing(achievement);
  }

  useEffect(() => {
    const onKey = (event) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="achievements-page" role="dialog" aria-modal="true" aria-label="Achievements">
      <div className="achievements-page__card">
        <button type="button" className="achievements-page__back" onClick={onClose}>
          ← Back
        </button>

        <p className="eyebrow">Progress</p>
        <h1>Achievements</h1>

        <div className="achievements-list">
          {locked.map((achievement) => {
            const progress = stats[achievement.statKey] || 0;
            const complete = progress >= achievement.target;
            const percent = Math.min(100, Math.round((progress / achievement.target) * 100));

            return (
              <div className="achievement-row" key={achievement.id}>
                <span className="achievement-row__icon" aria-hidden="true">{achievement.icon}</span>

                <div className="achievement-row__body">
                  <strong>{achievement.label}</strong>
                  <span className="achievement-row__desc">{achievement.description}</span>
                  <div className="achievement-row__track">
                    <div className="achievement-row__fill" style={{ width: `${percent}%` }} />
                  </div>
                  <span className="achievement-row__count">
                    {Math.min(progress, achievement.target)} / {achievement.target}
                  </span>
                </div>

                <button
                  type="button"
                  className="achievement-row__unlock"
                  disabled={!complete}
                  onClick={() => handleUnlock(achievement)}
                >
                  Unlock
                </button>
              </div>
            );
          })}

          {locked.length === 0 && (
            <p className="achievements-shelf__empty">Every quest is complete -- nice work!</p>
          )}
        </div>

        <div className="achievements-shelf">
          <p className="eyebrow">Unlocked Badges</p>

          <div className="achievements-shelf__grid">
            {unlocked.length === 0 && (
              <span className="achievements-shelf__empty">No badges yet -- complete a quest above.</span>
            )}

            {unlocked.map((achievement) => (
              <div className="achievement-badge" key={achievement.id}>
                <span className="achievement-badge__icon" aria-hidden="true">{achievement.icon}</span>
                <strong>{achievement.label}</strong>
              </div>
            ))}
          </div>
        </div>
      </div>

      <BadgeUnlockReveal achievement={revealing} onDone={() => setRevealing(null)} />
    </div>
  );
}
