// Persists each character's XP/level across sessions, so picking "Zombie"
// again later resumes exactly where that character left off instead of
// starting over at 0 XP.
import { scoped } from "./storageScope";

const CHARACTERS_KEY = "questverse_character_progress_v1";

function readJson(key, fallback) {
  try {
    const raw = localStorage.getItem(scoped(key));
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function writeJson(key, value) {
  try {
    localStorage.setItem(scoped(key), JSON.stringify(value));
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

// The character played most recently, with their saved XP/level -- what the
// stage map shows as "the player". Null if nothing has been played yet.
export function loadLastPlayedCharacter() {
  const all = readJson(CHARACTERS_KEY, {});
  const entries = Object.entries(all).filter(([, value]) => value?.lastPlayedAt);
  if (entries.length === 0) return null;
  entries.sort((a, b) => String(b[1].lastPlayedAt).localeCompare(String(a[1].lastPlayedAt)));
  const [characterId, value] = entries[0];
  return { characterId, ...DEFAULT_PROGRESS, ...value };
}
