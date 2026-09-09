import { useEffect, useRef, useState } from "react";
import XPBar from "../gamification/components/XPBar";
import StreakFlame from "../gamification/components/StreakFlame";
import AnswerFlash from "../gamification/components/AnswerFlash";
import BadgeToast from "../gamification/components/BadgeToast";
import { useGamification } from "../gamification/useGamification";
import { computeSessionStats } from "../utils/analytics";
import { QUEST_LENGTH } from "../questConfig";
import { getCharacter } from "../characters";

const QUESTION_SECONDS = 15;

export default function PlayScreen({ gameState, onAnswer, onExit }) {
  const [secondsLeft, setSecondsLeft] = useState(QUESTION_SECONDS);
  const [flashPhase, setFlashPhase] = useState(null);
  const [textAnswer, setTextAnswer] = useState("");
  const submittedRef = useRef(false);

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

  useEffect(() => {
    setSecondsLeft(QUESTION_SECONDS);
    setTextAnswer("");
    submittedRef.current = false;
    // Keyed on questionCount, not question.id: a thin content pool can
    // legitimately serve the same question twice in a row, and the
    // submit-lock/timer must still reset for that next round.
  }, [gameState.questionCount]);

  const isUntimed = question?.mode === "short_answer";

  // The result popup (win/wrong, with the descriptive feedback) now stays up
  // until the player clicks OK instead of auto-dismissing on a timer -- so
  // the game clock for the *next* question (which has already loaded
  // underneath it) must not tick while it's showing, or reading the
  // explanation would silently burn through the next question's time limit.
  const isPaused = Boolean(flashPhase);

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
  }, [gameState.questionCount, gameState.isLoading, gameState.gameComplete, question, isUntimed, isPaused]);

  useEffect(() => {
    if (secondsLeft > 0 || gameState.isLoading || gameState.gameComplete || submittedRef.current || isUntimed || isPaused) {
      return;
    }

    submittedRef.current = true;
    onAnswer(null, true);
  }, [secondsLeft, gameState.isLoading, gameState.gameComplete, onAnswer, isUntimed, isPaused]);

  useEffect(() => {
    if (!gameState.lastResult) {
      return undefined;
    }

    // Just pick the initial phase here -- no auto-dismiss timer. Dismissal
    // is driven by the player clicking OK (handleFlashAcknowledge below).
    setFlashPhase(gameState.lastResult.correct ? "win" : "wrong");
  }, [gameState.lastResult]);

  useEffect(() => {
    // "xpboost" is a short celebratory flourish with nothing left to read,
    // so it's fine for it to auto-dismiss rather than need its own OK click.
    if (flashPhase !== "xpboost") {
      return undefined;
    }

    const timerId = setTimeout(() => setFlashPhase(null), 1400);
    return () => clearTimeout(timerId);
  }, [flashPhase]);

  function handleFlashAcknowledge() {
    setFlashPhase((currentPhase) => (currentPhase === "win" ? "xpboost" : null));
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

      {gameState.gameComplete ? (
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
              <dt>Highest Tier</dt>
              <dd>{sessionStats.highestTier}</dd>
            </div>
            <div>
              <dt>Avg. Speed</dt>
              <dd>{sessionStats.avgSpeedSeconds}s</dd>
            </div>
          </dl>

          <button type="button" className="quest-complete__exit" onClick={onExit}>
            ◀ BACK TO START
          </button>
        </section>
      ) : <section className="question-card">
        <p className="question-number">
          Question {gameState.questionCount + 1}
        </p>

        <h1>{question.prompt}</h1>

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
        )}
      </section>}
    </main>
  );
}
