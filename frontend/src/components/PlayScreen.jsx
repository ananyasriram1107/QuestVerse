import { useEffect, useRef, useState } from "react";
import XPBar from "../gamification/components/XPBar";
import StreakFlame from "../gamification/components/StreakFlame";
import AnswerFlash from "../gamification/components/AnswerFlash";
import BadgeToast from "../gamification/components/BadgeToast";
import { useGamification } from "../gamification/useGamification";
import { computeSessionStats } from "../utils/analytics";
import Dashboard from "./Dashboard";
import { getCharacter } from "../characters";

const QUESTION_SECONDS = 15;

export default function PlayScreen({ gameState, onAnswer, onExit, onPractice, onRequestHint, onLevelDone }) {
  const QUEST_LENGTH = gameState.questLength;
  const [secondsLeft, setSecondsLeft] = useState(QUESTION_SECONDS);
  const [flashPhase, setFlashPhase] = useState(null);
  const [textAnswer, setTextAnswer] = useState("");
  const submittedRef = useRef(false);
  // Companion hint bubble: idle | loading | ready | error. Per question; never touches scoring.
  const [hintState, setHintState] = useState({ status: "idle", text: "", questionId: null });
  const hintInFlightRef = useRef(null); // question id of the request in flight -- blocks rapid double clicks

  // "Adjusting state during render" (see https://react.dev/learn/you-might-not-need-an-effect)
  // instead of an effect that calls setState -- avoids the extra render pass
  // that setState-in-effect causes for these per-question/per-result resets.
  const [prevAttemptCount, setPrevAttemptCount] = useState(gameState.attemptCount);
  const [prevLastResult, setPrevLastResult] = useState(gameState.lastResult);

  const question = gameState.currentQuestion;
  const correctCount = gameState.attempts.filter((attempt) => attempt.correct).length;
  const progress = Math.min(correctCount / QUEST_LENGTH, 1);
  const sessionStats = computeSessionStats(gameState.attempts);
  const character = getCharacter(gameState.characterId);

  const {
    progressPercent,
    streakLabel,
    activeBadge,
    dismissBadge,
  } = useGamification(gameState);

  // Keyed on attemptCount (every submission), not question.id or solved count: a thin content pool can
  // legitimately serve the same question twice in a row, and the
  // submit-lock/timer must still reset for that next round.
  if (prevAttemptCount !== gameState.attemptCount) {
    setPrevAttemptCount(gameState.attemptCount);
    setSecondsLeft(QUESTION_SECONDS);
    // Keep what the student typed after a miss so they can refine it; clear
    // it once the question is actually solved and the next one unlocks.
    if (gameState.lastResult?.question_solved) {
      setTextAnswer("");
    }
  }

  // A hint belongs to one question: moving on drops it (and any pause it caused).
  if (hintState.questionId !== null && hintState.questionId !== question?.id) {
    setHintState({ status: "idle", text: "", questionId: null });
  }

  // Ref mutation belongs in an effect, not render -- only the setState calls
  // above are safe to run directly during render.
  useEffect(() => {
    submittedRef.current = false;
  }, [gameState.attemptCount, gameState.error]);

  const hintVisible = hintState.status !== "idle" && hintState.questionId === question?.id;
  // The countdown holds still (keeping its exact remaining seconds) only while the hint
  // request is pending; it resumes the moment the hint or an error arrives.
  const hintPausesTimer = hintVisible && hintState.status === "loading";

  async function askForHint() {
    if (!question || hintInFlightRef.current === question.id || hintState.status === "loading") return;
    const questionId = question.id;
    hintInFlightRef.current = questionId;
    setHintState({ status: "loading", text: "", questionId });
    try {
      const text = await onRequestHint(questionId);
      setHintState((prev) => (prev.questionId === questionId ? { status: "ready", text, questionId } : prev));
    } catch (error) {
      setHintState((prev) =>
        prev.questionId === questionId ? { status: "error", text: error.message, questionId } : prev
      );
    } finally {
      if (hintInFlightRef.current === questionId) hintInFlightRef.current = null;
    }
  }

  function closeHint() {
    setHintState({ status: "idle", text: "", questionId: null });
  }

  const isUntimed = question?.mode === "short_answer";

  // The result popup (win/wrong, with the descriptive feedback) now stays up
  // until the player clicks OK instead of auto-dismissing on a timer -- so
  // the game clock for the *next* question (which has already loaded
  // underneath it) must not tick while it's showing, or reading the
  // explanation would silently burn through the next question's time limit.
  const isPaused = Boolean(flashPhase) || hintPausesTimer;

  useEffect(() => {
    if (!question || gameState.isLoading || gameState.gameComplete || isUntimed || isPaused) {
      return undefined;
    }

    const intervalId = setInterval(() => {
      // Pure countdown only -- no side effects here. Calling onAnswer (which
      // dispatches into App) from inside a setState updater runs it during
      // React's render phase for PlayScreen and triggers "Cannot update a
      // component while rendering a different component". The timeout
      // submission is handled by the effect below instead, reacting to
      // secondsLeft actually reaching 0.
      setSecondsLeft((currentSeconds) => Math.max(0, currentSeconds - 1));
    }, 1000);

    return () => clearInterval(intervalId);
  }, [gameState.attemptCount, gameState.isLoading, gameState.gameComplete, question, isUntimed, isPaused]);

  useEffect(() => {
    if (secondsLeft > 0 || gameState.isLoading || gameState.gameComplete || submittedRef.current || isUntimed || isPaused) {
      return;
    }

    submittedRef.current = true;
    onAnswer(null, true);
  }, [secondsLeft, gameState.isLoading, gameState.gameComplete, onAnswer, isUntimed, isPaused]);

  // Just pick the initial phase here -- no auto-dismiss timer. Dismissal
  // is driven by the player clicking OK (handleFlashAcknowledge below).
  if (prevLastResult !== gameState.lastResult) {
    setPrevLastResult(gameState.lastResult);
    if (gameState.lastResult) {
      setFlashPhase(gameState.lastResult.correct ? "win" : "wrong");
    }
  }

  useEffect(() => {
    // "xpboost" is a short celebratory flourish with nothing left to read,
    // so it's fine for it to auto-dismiss rather than need its own OK click.
    if (flashPhase !== "xpboost") {
      return undefined;
    }

    const timerId = setTimeout(() => setFlashPhase(null), 1400);
    return () => clearTimeout(timerId);
  }, [flashPhase]);

  // A level's final answer still gets its feedback popup (and XP flourish);
  // once that has been dismissed the app moves on to the results screen.
  useEffect(() => {
    if (gameState.levelId && gameState.gameComplete && !flashPhase) {
      onLevelDone?.();
    }
  }, [gameState.levelId, gameState.gameComplete, flashPhase, onLevelDone]);

  // The XP flourish only plays when XP was actually awarded (a replayed level
  // question earns none, and the backend says so).
  function handleFlashAcknowledge() {
    const earned = gameState.lastResult?.xp_earned ?? 0;
    setFlashPhase((currentPhase) => (currentPhase === "win" && earned > 0 ? "xpboost" : null));
  }

  function chooseAnswer(answer) {
    if (gameState.isLoading || submittedRef.current) {
      return;
    }

    submittedRef.current = true;
    onAnswer(answer, false);
  }

  function submitTextAnswer(event) {
    event.preventDefault();

    if (gameState.isLoading || submittedRef.current || !textAnswer.trim()) {
      return;
    }

    submittedRef.current = true;
    onAnswer(textAnswer, false);
  }

  if (gameState.isLoading && !question) {
    return (
      <main className="loading-screen">
        <button type="button" className="exit-button" onClick={onExit}>
          ◀ EXIT
        </button>
        Loading your first question…
      </main>
    );
  }

  if (!question && !gameState.gameComplete) {
    return (
      <main className="loading-screen">
        <button type="button" className="exit-button" onClick={onExit}>
          ◀ EXIT
        </button>
        No question is available. Please restart the game.
      </main>
    );
  }

  return (
    <main className="play-screen">
      <button type="button" className="exit-button" onClick={onExit}>
        ◀ EXIT
      </button>

      <header className="game-header">
        <div>
          <span className="eyebrow">Player</span>
          <strong>{gameState.name}</strong>
        </div>

        <div>
          <span className="eyebrow">Tier</span>
          <strong>{gameState.tier}</strong>
        </div>

        <XPBar
          xp={gameState.totalXp}
          level={gameState.level}
          progressPercent={progressPercent}
        />

        <div className={!isUntimed && secondsLeft <= 5 ? "timer timer--urgent" : "timer"}>
          <span className="eyebrow">Time</span>
          <strong>{isUntimed ? "No limit" : `${secondsLeft}s`}</strong>
        </div>
      </header>

      <StreakFlame
        streak={gameState.correctStreak}
        label={streakLabel}
      />

      <AnswerFlash
        phase={flashPhase}
        score={gameState.totalXp}
        xp={gameState.lastResult?.xp_earned}
        feedback={gameState.lastResult?.evaluation?.feedback ?? gameState.lastResult?.evaluation?.explanation}
        onDismiss={handleFlashAcknowledge}
      />

      <BadgeToast badge={activeBadge} onClose={dismissBadge} />

      {gameState.error && (
        <p className="connection-error">{gameState.error}</p>
      )}

      <section className="quest-journey" aria-label={`Quest progress: ${gameState.questionCount} of ${QUEST_LENGTH} questions`}>
        <div className="quest-ambience quest-ambience--one" aria-hidden="true">
          <i className="ambient-star ambient-star--one" />
          <i className="ambient-star ambient-star--two" />
          <i className="ambient-leaf ambient-leaf--one" />
          <i className="ambient-flower ambient-flower--one" />
        </div>
        <div className="quest-ambience quest-ambience--two" aria-hidden="true">
          <i className="ambient-star ambient-star--one" />
          <i className="ambient-star ambient-star--two" />
          <i className="ambient-leaf ambient-leaf--one" />
          <i className="ambient-flower ambient-flower--one" />
        </div>
        <div className="quest-journey__path" />
        <div className="quest-journey__milestones" aria-hidden="true">
          {Array.from({ length: QUEST_LENGTH }, (_, index) => (
            <span className={index < gameState.questionCount ? "is-cleared" : ""} key={index} />
          ))}
        </div>
        <div className="pixel-explorer" style={{ "--journey-position": `${7 + progress * 79}%` }} aria-hidden="true">
          {character.spriteType === "image" ? (
            <img className="pixel-explorer__sprite" src={character.spriteSrc} alt="" />
          ) : (
            <span className="pixel-explorer__sprite pixel-explorer__sprite--emoji">
              {character.spriteValue}
            </span>
          )}
        </div>
        <div className={gameState.gameComplete ? "treasure-chest treasure-chest--open" : "treasure-chest"} aria-label={gameState.gameComplete ? "Opened treasure" : "Treasure ahead"}>
          <span className="treasure-chest__lid" />
          <span className="treasure-chest__base" />
          {gameState.gameComplete && <span className="treasure-chest__glow" aria-hidden="true" />}
        </div>
      </section>

      {gameState.gameComplete && gameState.levelId ? (
        <p className="level-finishing" role="status">Level cleared! Tallying your results…</p>
      ) : gameState.gameComplete ? (
        <section className="quest-complete" aria-live="polite">
          <div className="pixel-confetti" aria-hidden="true">
            {Array.from({ length: 18 }, (_, index) => <i key={index} style={{ "--confetti-index": index }} />)}
          </div>
          <p>Quest complete</p>
          <h1>Treasure unlocked!</h1>
          <strong>{gameState.totalXp} XP</strong>
          <span>You reached the treasure chest.</span>

          <dl className="session-stats">
            <div>
              <dt>Accuracy</dt>
              <dd>{sessionStats.accuracy}%</dd>
            </div>
            <div>
              <dt>Longest Streak</dt>
              <dd>{sessionStats.longestStreak}</dd>
            </div>
            <div>
              <dt>Retries</dt>
              <dd>{sessionStats.totalAnswered - sessionStats.correctCount}</dd>
            </div>
            <div>
              <dt>Highest Tier</dt>
              <dd>{sessionStats.highestTier}</dd>
            </div>
            <div>
              <dt>Avg. Speed</dt>
              <dd>{sessionStats.avgSpeedSeconds}s</dd>
            </div>
          </dl>

          {gameState.sessionId && (
            <Dashboard sessionId={gameState.sessionId} studentId={gameState.characterId} onPractice={onPractice} />
          )}

          <button type="button" className="quest-complete__exit" onClick={onExit}>
            ◀ BACK TO START
          </button>
        </section>
      ) : <section className="question-card">
        <p className="question-number">
          Question {gameState.questionCount + 1}
        </p>

        <h1>{question.prompt}</h1>

        {onRequestHint && gameState.sessionId && (
          <div className="hint-companion">
            <button
              type="button"
              className="hint-button"
              onClick={askForHint}
              disabled={gameState.isLoading || (hintVisible && hintState.status === "loading")}
            >
              GET A HINT 💡
            </button>
            {hintVisible && (
              <div className={`hint-bubble hint-bubble--${hintState.status}`} role="status" aria-live="polite">
                <span className="hint-bubble__who" aria-hidden="true">
                  {character.spriteType === "image" ? "🧙" : character.spriteValue}
                </span>
                <p>{hintState.status === "loading" ? "Your companion is thinking…" : hintState.text}</p>
                <div className="hint-bubble__actions">
                  {hintState.status !== "loading" && (
                    <button type="button" onClick={closeHint}>
                      GOT IT
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {question.mode === "short_answer" ? (
          <form className="short-answer-form" onSubmit={submitTextAnswer}>
            <textarea
              className="short-answer-input"
              value={textAnswer}
              onChange={(event) => setTextAnswer(event.target.value)}
              placeholder="Type your answer…"
              disabled={gameState.isLoading}
              autoFocus
            />
            <button
              type="submit"
              className="short-answer-submit"
              disabled={gameState.isLoading || !textAnswer.trim()}
            >
              Submit Answer
            </button>
          </form>
        ) : (
          <div className="answer-options-wrap">
          <div className="answer-options">
            {(question.options || []).map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => chooseAnswer(option)}
                disabled={gameState.isLoading}
              >
                {option}
              </button>
            ))}
          </div>
          </div>
        )}
      </section>}
    </main>
  );
}
