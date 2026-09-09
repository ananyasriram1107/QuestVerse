// Lifetime stats (across every session/character/course) that achievement
// progress bars are measured against, plus which achievements the player
// has actually claimed via the Unlock button. Two separate concerns: stats
// grow automatically as the player answers questions, but an achievement
// only moves into the "unlocked" shelf once explicitly claimed.
const STATS_KEY = "questverse_lifetime_stats_v1";
const UNLOCKED_KEY = "questverse_unlocked_achievements_v1";

const DEFAULT_STATS = {
  totalAnswered: 0,
  totalMcqAnswered: 0,
  totalShortAnswered: 0,
  totalCorrect: 0,
  longestStreakEver: 0,
};

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

export function loadStats() {
  return { ...DEFAULT_STATS, ...readJson(STATS_KEY, {}) };
}

// Called once per answered question (mcq or short_answer, including
// timeouts -- the round was still completed).
export function recordAnswer({ mode, correct, correctStreakAfter }) {
  const stats = loadStats();

  stats.totalAnswered += 1;
  if (mode === "mcq") {
    stats.totalMcqAnswered += 1;
  } else if (mode === "short_answer") {
    stats.totalShortAnswered += 1;
  }
  if (correct) {
    stats.totalCorrect += 1;
  }
  stats.longestStreakEver = Math.max(stats.longestStreakEver, correctStreakAfter || 0);

  writeJson(STATS_KEY, stats);
  return stats;
}

export function loadUnlockedAchievements() {
  return readJson(UNLOCKED_KEY, []);
}

export function unlockAchievement(id) {
  const unlocked = new Set(loadUnlockedAchievements());
  unlocked.add(id);
  const result = [...unlocked];
  writeJson(UNLOCKED_KEY, result);
  return result;
}
