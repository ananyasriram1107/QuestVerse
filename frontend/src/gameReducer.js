export const initialGameState = {
  name: "",
  characterId: null,
  courseId: null,
  courseTitle: null,
  mode: null,
  started: false,
  tier: 1,
  correctStreak: 0,
  wrongStreak: 0,
  totalXp: 0,
  level: 1,
  currentQuestion: null,
  lastResult: null,
  attempts: [],
  questionCount: 0, // questions SOLVED so far (server-authoritative)
  attemptCount: 0, // every submission, right or wrong -- resets per-attempt UI
  sessionId: null,
  levelId: null, // set when the quiz is a level of the world map
  questLength: 5,
  hint: null,
  gameComplete: false,
  isLoading: false,
  error: null,
};

export function gameReducer(state, action) {
  switch (action.type) {
    case "START_GAME":
      return {
        ...state,
        name: action.payload.name,
        characterId: action.payload.characterId,
        courseId: action.payload.courseId,
        courseTitle: action.payload.courseTitle,
        mode: action.payload.mode,
        totalXp: action.payload.totalXp ?? 0,
        level: action.payload.level ?? 1,
        started: true,
        isLoading: true,
        error: null,
      };

    case "QUESTION_LOADED":
      return {
        ...state,
        currentQuestion: action.payload.question,
        sessionId: action.payload.sessionId ?? state.sessionId,
        questLength: action.payload.questLength ?? state.questLength,
        isLoading: false,
        error: null,
      };

    case "ANSWER_SUBMITTING":
      return {
        ...state,
        isLoading: true,
        error: null,
      };

    case "ANSWER_RESULT": {
      const result = action.payload;

      return {
        ...state,
        tier: result.tier,
        correctStreak: result.correct_streak,
        wrongStreak: result.wrong_streak,
        totalXp: result.total_xp,
        level: result.level,
        lastResult: result,
        // A wrong answer comes back with the SAME question (nothing unlocked).
        currentQuestion: result.game_complete ? null : result.next_question,
        hint: result.hint ?? null,
        attempts: [
          ...state.attempts,
          {
            correct: result.correct,
            tier: state.currentQuestion?.tier ?? result.tier,
            time_taken_ms: result.time_taken_ms,
          },
        ],
        questionCount: result.solved_count,
        attemptCount: state.attemptCount + 1,
        gameComplete: result.game_complete,
        isLoading: false,
        error: null,
      };
    }

    case "RESUME_SESSION": {
      const snap = action.payload;
      return {
        ...state,
        ...snap.identity,
        started: true,
        sessionId: snap.session_id,
        questLength: snap.quest_length,
        tier: snap.tier,
        correctStreak: snap.correct_streak,
        wrongStreak: snap.wrong_streak,
        totalXp: snap.total_xp,
        level: snap.level,
        currentQuestion: snap.game_complete ? null : snap.question,
        hint: snap.hint ?? null,
        attempts: snap.attempts.map((a) => ({ correct: a.correct, tier: a.tier, time_taken_ms: a.time_taken_ms })),
        questionCount: snap.solved_count,
        attemptCount: snap.attempts.length,
        gameComplete: snap.game_complete,
        isLoading: false,
        error: null,
      };
    }

    case "REQUEST_FAILED":
      return {
        ...state,
        isLoading: false,
        error: action.payload.message,
      };

    case "RESET_GAME":
      return initialGameState;

    default:
      return state;
  }
}
