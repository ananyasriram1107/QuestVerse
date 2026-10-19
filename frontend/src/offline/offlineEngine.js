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

const QUEST_LENGTH = 5;

// Offline mirror of backend/quest_session.py: one in-browser session that
// only unlocks the next question once the current one is solved. (Offline
// Mode is client-side by nature, so this is behavioural parity, not a
// security boundary -- the real enforcement is on the backend.)
let offlineSession = null;

// The wrong options, decided from the question's real correct_answer.
function incorrectOptions(question) {
  const right = String(question.correct_answer).trim().toLowerCase();
  return question.options.filter((o) => o.trim().toLowerCase() !== right);
}

// Exactly two wrong options go, and the correct answer plus at least one wrong
// one must remain, so three or more wrong options must still be standing.
function fiftyFiftyAvailable(question) {
  const s = offlineSession;
  if (!question || question.mode !== "mcq" || s.fiftyUsed) return false;
  return incorrectOptions(question).filter((o) => !s.eliminated.includes(o)).length >= 3;
}

export function fiftyFiftyOffline(payload) {
  const s = offlineSession;
  if (!s || String(payload.question_id) !== s.currentId) {
    throw new Error("That question is not currently unlocked");
  }
  const question = QUESTIONS_BY_ID.get(String(payload.question_id));
  if (question.mode !== "mcq") throw new Error("50/50 is only available on multiple-choice questions");
  if (s.fiftyUsed) throw new Error("You already used 50/50 on this question");
  if (!fiftyFiftyAvailable(question)) {
    throw new Error("50/50 is not available now: too few wrong options are left to remove two safely");
  }
  const candidates = incorrectOptions(question).filter((o) => !s.eliminated.includes(o));
  for (let i = 0; i < 2; i += 1) {
    s.eliminated.push(candidates.splice(Math.floor(Math.random() * candidates.length), 1)[0]);
  }
  s.fiftyUsed = true;
  s.hint = "50/50 used: two wrong options were removed. The correct answer is one of the options still showing.";
  return { removed_count: 2, hint: s.hint, next_question: offlineView().next_question };
}

function offlineView(extra = {}) {
  const s = offlineSession;
  const current = s.currentId ? QUESTIONS_BY_ID.get(s.currentId) : null;
  const question = current ? publicQuestion(current) : null;
  if (question && s.eliminated.length) question.eliminated_options = [...s.eliminated];
  if (question) question.fifty_fifty_available = fiftyFiftyAvailable(current);
  return {
    quest_length: QUEST_LENGTH,
    solved_count: s.solved.length,
    game_complete: s.solved.length >= QUEST_LENGTH,
    tier: s.tier,
    correct_streak: s.correctStreak,
    wrong_streak: s.wrongStreak,
    total_xp: s.startXp + s.xpEarned,
    level: levelFromXp(s.startXp + s.xpEarned),
    attempts: s.attempts,
    next_question: question,
    ...extra,
  };
}

function offlineHint(question, attemptNo, evaluation, answer, struck) {
  if (question.mode === "mcq") {
    const pieces = [];
    if (answer === null || answer === undefined) pieces.push("Time ran out.");
    pieces.push(question.hint || "Reason from the core definition behind the question rather than what merely sounds familiar.");
    if (struck) pieces.push("The option you chose is greyed out because it is not correct.");
    return pieces.join(" ");
  }
  const matched = evaluation.matched_concepts || [];
  const missing = evaluation.missing_concepts || [];
  if (missing.length) {
    const prefix = matched.length ? `You've covered ${matched.join(", ")}. ` : "";
    return `${prefix}Not quite there yet -- think about: ${missing.slice(0, Math.max(1, attemptNo)).join(", ")}.`;
  }
  return "Not quite -- re-read the question and be more specific about the exact term or value it asks for.";
}

export function getFirstQuestionOffline(courseId = DEFAULT_COURSE, mode = DEFAULT_MODE, startXp = 0) {
  const q = randomQuestionFor(courseId, mode, 1);
  offlineSession = {
    courseId: q.courseId, mode: q.mode, tier: 1, correctStreak: 0, wrongStreak: 0,
    startXp: Math.max(0, Number(startXp) || 0), xpEarned: 0,
    currentId: String(q.id), solved: [], attempts: [], attemptsOnCurrent: 0, eliminated: [], fiftyUsed: false, hint: null,
    servedAt: Date.now(),
  };
  const view = offlineView();
  const { next_question: firstQuestion, ...sessionFields } = view;
  return { ...firstQuestion, ...sessionFields };
}

export function submitAnswerOffline(payload) {
  const s = offlineSession;
  if (!s || String(payload.question_id) !== s.currentId) {
    throw new Error("That question is not currently unlocked");
  }
  const question = QUESTIONS_BY_ID.get(String(payload.question_id));
  if (!question) {
    throw new Error("Unknown question_id");
  }

  const [isCorrect, evaluation] = gradeOffline(question, payload.answer);
  if (question.mode === "mcq" && payload.answer != null && s.eliminated.includes(payload.answer)) {
    throw new Error("That option has been eliminated and can't be selected");
  }
  const optionsShown = question.mode === "mcq" ? question.options.length - s.eliminated.length : null;
  const oldLevel = levelFromXp(s.startXp + s.xpEarned);
  const result = nextState(s.tier, s.correctStreak, s.wrongStreak, isCorrect);
  s.tier = result.tier;
  s.correctStreak = result.correctStreak;
  s.wrongStreak = result.wrongStreak;
  s.attemptsOnCurrent += 1;
  s.attempts.push({
    question_id: String(question.id), correct: isCorrect, tier: question.tier,
    attempt_no: s.attemptsOnCurrent, time_taken_ms: Date.now() - s.servedAt,
    mode: question.mode, n_options: optionsShown,
  });

  if (!isCorrect) {
    // Exactly one option is greyed out: the wrong one the student picked.
    // Anything more only comes from an explicit 50/50 request.
    let struck = null;
    if (question.mode === "mcq") {
      struck = incorrectOptions(question).find((o) => o === payload.answer && !s.eliminated.includes(o)) ?? null;
      if (struck) s.eliminated.push(struck);
    }
    const hint = offlineHint(question, s.attemptsOnCurrent, evaluation, payload.answer, struck);
    return offlineView({
      correct: false,
      evaluation: { your_answer: payload.answer, feedback: hint, accuracy: evaluation.accuracy },
      question_solved: false, xp_earned: 0, level_up: false, hint,
    });
  }

  let xp = 0;
  if (!s.solved.includes(s.currentId)) {
    s.solved.push(s.currentId);
    xp = result.xpEarned;
    s.xpEarned += xp;
  }
  s.eliminated = [];
  s.fiftyUsed = false;
  s.attemptsOnCurrent = 0;
  s.servedAt = Date.now();
  if (s.solved.length >= QUEST_LENGTH) {
    s.currentId = null;
  } else {
    let next = randomQuestionFor(s.courseId, s.mode, s.tier, question.id);
    for (let i = 0; i < 20 && s.solved.includes(String(next.id)); i += 1) {
      next = randomQuestionFor(s.courseId, s.mode, s.tier, question.id);
    }
    s.currentId = String(next.id);
  }
  return offlineView({
    correct: true, evaluation, question_solved: true, xp_earned: xp,
    level_up: levelFromXp(s.startXp + s.xpEarned) > oldLevel, hint: null,
  });
}

export function hasOfflineQuestion(questionId) {
  return QUESTIONS_BY_ID.has(String(questionId));
}
