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
  questionCount: 0,
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
        currentQuestion: action.payload.gameComplete ? null : result.next_question,
        attempts: [
          ...state.attempts,
          {
            correct: result.correct,
            tier: result.tier,
            time_taken_ms: result.time_taken_ms,
          },
        ],
        questionCount: state.questionCount + 1,
        gameComplete: action.payload.gameComplete,
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
