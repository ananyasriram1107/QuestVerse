// Lifetime stats (across every session/character/course) that achievement
// progress bars are measured against, plus which achievements the player
// has actually claimed via the Unlock button. Two separate concerns: stats
// grow automatically as the player answers questions, but an achievement
// only moves into the "unlocked" shelf once explicitly claimed.
import { getServerAchievements, putServerAchievements } from "../api";
import { scoped } from "./storageScope";

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
  schedulePush();
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
  schedulePush();
  return result;
}

// ---- Server copy (recorded per user in the database) ----
let pushTimer = null;

function schedulePush() {
  clearTimeout(pushTimer);
  pushTimer = setTimeout(() => {
    putServerAchievements({ stats: loadStats(), unlocked: loadUnlockedAchievements() }).catch(() => {
      // offline or signed out -- the next change (or next login sync) sends it again
    });
  }, 800);
}

// After login: take the larger of the browser's and the server's numbers and the union of
// unlocks, save that locally, and send back anything the server was missing.
export async function syncAchievementsWithServer() {
  try {
    const remote = await getServerAchievements();
    const local = loadStats();
    const merged = { ...local };
    for (const [key, value] of Object.entries(remote.stats || {})) {
      merged[key] = Math.max(local[key] || 0, value || 0);
    }
    writeJson(STATS_KEY, merged);
    const ids = new Set([...loadUnlockedAchievements(), ...(remote.unlocked || []).map((u) => u.id)]);
    writeJson(UNLOCKED_KEY, [...ids]);
    schedulePush();
  } catch {
    // the server being unreachable must never block playing
  }
}
