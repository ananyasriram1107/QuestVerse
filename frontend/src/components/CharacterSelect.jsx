import { useEffect, useState } from "react";
import { CHARACTERS } from "../characters";
import { getProgress } from "../api";
import { loadCharacterProgress } from "../utils/characterStore";

export default function CharacterSelect({ onSelect, loading, onExit, courseTitle, showLevelProgress = false }) {
  // Each hero's saved level progress lives on the backend under their id.
  const [levelStats, setLevelStats] = useState({});

  useEffect(() => {
    if (!showLevelProgress) return undefined;
    let cancelled = false;
    CHARACTERS.forEach((character) => {
      getProgress(character.id)
        .then((data) => !cancelled && setLevelStats((prev) => ({ ...prev, [character.id]: data })))
        .catch(() => {});
    });
    return () => {
      cancelled = true;
    };
  }, [showLevelProgress]);

  return (
    <main className="character-select">
      {onExit && (
        <button type="button" className="exit-button" onClick={onExit}>
          ◀ EXIT
        </button>
      )}

      <section className="character-select__card">
        <p className="eyebrow">Adaptive Learning Quest</p>
        <h1>{courseTitle || "QuestVerse"}</h1>
        <p>Choose your character to begin.</p>

        <div className="character-grid">
          {CHARACTERS.map((character) => {
            const saved = loadCharacterProgress(character.id);
            const hasPlayed = saved.gamesPlayed > 0;

            return (
              <button
                key={character.id}
                type="button"
                className="character-card"
                onClick={() => onSelect(character)}
                disabled={loading}
              >
                <span className="character-card__sprite" aria-hidden="true">
                  {character.spriteType === "image" ? (
                    <img src={character.spriteSrc} alt="" />
                  ) : (
                    character.spriteValue
                  )}
                </span>
                <strong className="character-card__label">{character.label}</strong>
                <span className="character-card__blurb">{character.blurb}</span>
                <span className="character-card__stats">
                  {hasPlayed ? `Level ${saved.level} · ${saved.totalXp} XP` : "New Adventurer"}
                </span>
                {levelStats[character.id] && (
                  <span className="character-card__stats">
                    {levelStats[character.id].totals.levels_completed}/{levelStats[character.id].totals.levels_total} levels cleared
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </section>
    </main>
  );
}
