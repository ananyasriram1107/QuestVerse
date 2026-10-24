// Persists per-course mastery and earned badges across sessions so the
// Dashboard can show real progress for every subject, not just the one
// course played in the current session (each session only covers one
// courseId -- see Frontpage.jsx).
import { scoped } from "./storageScope";

const PROGRESS_KEY = "questverse_progress_v1";
const BADGES_KEY = "questverse_badges_v1";

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

export function loadProgress() {
  return readJson(PROGRESS_KEY, {});
}

// Merges this session's stats into the best-ever result for that course.
export function recordCourseSession(courseId, stats) {
  const all = loadProgress();
  const prev = all[courseId];

  all[courseId] = {
    accuracy: Math.max(prev?.accuracy ?? 0, stats.accuracy),
    highestTier: Math.max(prev?.highestTier ?? 1, stats.highestTier),
    sessionsPlayed: (prev?.sessionsPlayed ?? 0) + 1,
  };

  writeJson(PROGRESS_KEY, all);
  return all;
}

export function loadEarnedBadges() {
  return readJson(BADGES_KEY, []);
}

export function addEarnedBadges(codes) {
  const merged = new Set([...loadEarnedBadges(), ...codes]);
  const result = [...merged];
  writeJson(BADGES_KEY, result);
  return result;
}
