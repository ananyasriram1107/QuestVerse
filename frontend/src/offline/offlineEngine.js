// JS port of backend/main.py -- serves the exact same response shapes as
// the real /question/first and /answer endpoints, but entirely in-browser.
// This is what powers Offline Mode (utils/offlineMode.js) and also the
// automatic fallback in api.js when the real backend can't be reached.
import {
  OS_QUESTIONS, OS_SHORT_ANSWER,
  DBMS_QUESTIONS, DBMS_SHORT_ANSWER,
  DSA_QUESTIONS, DSA_SHORT_ANSWER,
} from "./courseContent";
import { LANG_MCQ_QUESTIONS, LANG_SHORT_ANSWER_QUESTIONS } from "./languageQuestions";
import { gradeOffline } from "./offlineGrading";

const ALL_QUESTIONS = [
  ...OS_QUESTIONS, ...OS_SHORT_ANSWER,
  ...DBMS_QUESTIONS, ...DBMS_SHORT_ANSWER,
  ...DSA_QUESTIONS, ...DSA_SHORT_ANSWER,
  ...LANG_MCQ_QUESTIONS, ...LANG_SHORT_ANSWER_QUESTIONS,
];

const QUESTIONS_BY_ID = new Map(ALL_QUESTIONS.map((q) => [String(q.id), q]));

// (courseId, mode) -> questions, and -> {tier: questions}, mirroring the
// backend's QUESTIONS_BY_COURSE_MODE / QUESTIONS_BY_COURSE_MODE_TIER.
const byMode = new Map();
const byModeTier = new Map();
for (const q of ALL_QUESTIONS) {
  const key = `${q.courseId}:${q.mode}`;
  if (!byMode.has(key)) byMode.set(key, []);
  byMode.get(key).push(q);

  if (!byModeTier.has(key)) byModeTier.set(key, new Map());
  const tierMap = byModeTier.get(key);
  if (!tierMap.has(q.tier)) tierMap.set(q.tier, []);
  tierMap.get(q.tier).push(q);
}

const DEFAULT_COURSE = "os";
const DEFAULT_MODE = "mcq";

function publicQuestion(q) {
  const base = {
    id: q.id,
    prompt: q.prompt,
    tier: q.tier,
    mode: q.mode,
    courseId: q.courseId,
  };
  if (q.mode === "mcq") {
    base.options = q.options;
  }
  return base;
}

function randomQuestionFor(courseId, mode, tier, excludeId) {
  let key = `${courseId}:${mode}`;
  if (!byMode.has(key)) {
    key = `${DEFAULT_COURSE}:${DEFAULT_MODE}`;
  }

  const tierMap = byModeTier.get(key) || new Map();
  let pool = tierMap.get(tier) || [];
  if (pool.length === 0) {
    for (const fallbackTier of [2, 1, 3]) {
      if (tierMap.get(fallbackTier)?.length) {
        pool = tierMap.get(fallbackTier);
        break;
      }
    }
  }
  if (pool.length === 0) {
    pool = byMode.get(key) || [];
  }

  const candidates = pool.filter((q) => q.id !== excludeId);
  const finalPool = candidates.length > 0 ? candidates : pool;
  return finalPool[Math.floor(Math.random() * finalPool.length)];
}

// Mirrors backend/engine.py's next_state.
function nextState(tier, correctStreak, wrongStreak, correct) {
  if (correct) {
    correctStreak += 1;
    wrongStreak = 0;
    const xpEarned = tier * 10;
    if (correctStreak >= 2) {
      tier = Math.min(3, tier + 1);
      correctStreak = 0;
    }
    return { tier, correctStreak, wrongStreak, xpEarned };
  }

  wrongStreak += 1;
  correctStreak = 0;
  if (wrongStreak >= 2) {
    tier = Math.max(1, tier - 1);
    wrongStreak = 0;
  }
  return { tier, correctStreak, wrongStreak, xpEarned: 0 };
}

// Mirrors backend/engine.py's level_from_xp.
function levelFromXp(totalXp) {
  return Math.floor(Math.sqrt(totalXp / 50)) + 1;
}

export function getFirstQuestionOffline(courseId = DEFAULT_COURSE, mode = DEFAULT_MODE) {
  const q = randomQuestionFor(courseId, mode, 1);
  return publicQuestion(q);
}

export function submitAnswerOffline(payload) {
  const question = QUESTIONS_BY_ID.get(String(payload.question_id));
  if (!question) {
    throw new Error("Unknown question_id");
  }

  const safeTier = Math.max(1, Math.min(3, payload.tier));
  const [isCorrect, evaluation] = gradeOffline(question, payload.answer);

  const result = nextState(safeTier, payload.correct_streak, payload.wrong_streak, isCorrect);
  const newTotalXp = payload.total_xp + result.xpEarned;
  const oldLevel = levelFromXp(payload.total_xp);
  const newLevel = levelFromXp(newTotalXp);

  const nextQ = randomQuestionFor(question.courseId, question.mode, result.tier, question.id);

  return {
    correct: isCorrect,
    evaluation,
    xp_earned: result.xpEarned,
    total_xp: newTotalXp,
    tier: result.tier,
    correct_streak: result.correctStreak,
    wrong_streak: result.wrongStreak,
    level: newLevel,
    level_up: newLevel > oldLevel,
    next_question: publicQuestion(nextQ),
  };
}

export function hasOfflineQuestion(questionId) {
  return QUESTIONS_BY_ID.has(String(questionId));
}
