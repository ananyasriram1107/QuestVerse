// Persists each character's XP/level across sessions, so picking "Zombie"
// again later resumes exactly where that character left off instead of
// starting over at 0 XP.
const CHARACTERS_KEY = "questverse_character_progress_v1";

function readJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function writeJson(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // localStorage unavailable (private browsing, etc.) -- fail silently
  }
}

const DEFAULT_PROGRESS = { totalXp: 0, level: 1, gamesPlayed: 0, lastPlayedAt: null };

export function loadCharacterProgress(characterId) {
  const all = readJson(CHARACTERS_KEY, {});
  return all[characterId] ? { ...DEFAULT_PROGRESS, ...all[characterId] } : { ...DEFAULT_PROGRESS };
}

// Merges `updates` into that character's saved record (e.g. just totalXp/level
// as they change, or gamesPlayed when a new run starts).
export function saveCharacterProgress(characterId, updates) {
  const all = readJson(CHARACTERS_KEY, {});
  const current = all[characterId] ? { ...DEFAULT_PROGRESS, ...all[characterId] } : { ...DEFAULT_PROGRESS };

  all[characterId] = {
    ...current,
    ...updates,
    lastPlayedAt: new Date().toISOString(),
  };

  writeJson(CHARACTERS_KEY, all);
  return all[characterId];
}
