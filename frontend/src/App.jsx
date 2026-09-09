import { useEffect, useReducer, useRef, useState } from "react";
import FrontPage from "./pages/Frontpage";
import CharacterSelect from "./components/CharacterSelect";
import PlayScreen from "./components/PlayScreen";
import ClickSound from "./components/ClickSound";
import FullscreenToggle from "./components/FullscreenToggle";
import AchievementsToggle from "./components/AchievementsToggle";
import AchievementsPage from "./components/AchievementsPage";
import OfflineToggle from "./components/OfflineToggle";
import { getFirstQuestion, submitAnswer } from "./api";
import { gameReducer, initialGameState } from "./gameReducer";
import { QUEST_LENGTH } from "./questConfig";
import { computeSessionStats } from "./utils/analytics";
import { recordCourseSession } from "./utils/progressStore";
import { loadCharacterProgress, saveCharacterProgress } from "./utils/characterStore";
import { recordAnswer } from "./utils/achievementStore";
import "./App.css";

function WorldMotion() {
  return (
    <div className="world-motion" aria-hidden="true">
      <i className="world-motion__leaf world-motion__leaf--one" />
      <i className="world-motion__leaf world-motion__leaf--two" />
      <i className="world-motion__spark world-motion__spark--one" />
      <i className="world-motion__spark world-motion__spark--two" />
    </div>
  );
}

export default function App() {
  const [gameState, dispatch] = useReducer(gameReducer, initialGameState);
  const questionStartedAtRef = useRef(Date.now());
  const [session, setSession] = useState(null);
  const [showAchievements, setShowAchievements] = useState(false);
  const progressRecordedRef = useRef(false);

  useEffect(() => {
    if (gameState.currentQuestion?.id) {
      questionStartedAtRef.current = Date.now();
    }
  }, [gameState.currentQuestion?.id]);

  useEffect(() => {
    if (gameState.gameComplete && !progressRecordedRef.current && gameState.courseId) {
      progressRecordedRef.current = true;
      recordCourseSession(gameState.courseId, computeSessionStats(gameState.attempts));
    }
  }, [gameState.gameComplete, gameState.courseId, gameState.attempts]);

  // Keeps the active character's save file (XP/level) up to date as the
  // player earns XP, not just at the end of a completed quest -- so
  // progress isn't lost if they exit mid-quest.
  useEffect(() => {
    if (gameState.started && gameState.characterId) {
      saveCharacterProgress(gameState.characterId, {
        totalXp: gameState.totalXp,
        level: gameState.level,
      });
    }
  }, [gameState.started, gameState.characterId, gameState.totalXp, gameState.level]);

  function handleLaunchSession(config) {
    setSession(config);
  }

  function handleExitToStart() {
    progressRecordedRef.current = false;
    dispatch({ type: "RESET_GAME" });
    setSession(null);
  }

  async function startGame(character) {
    const saved = loadCharacterProgress(character.id);
    saveCharacterProgress(character.id, { gamesPlayed: saved.gamesPlayed + 1 });

    dispatch({
      type: "START_GAME",
      payload: {
        name: character.label,
        characterId: character.id,
        courseId: session?.courseId,
        courseTitle: session?.courseTitle,
        mode: session?.mode,
        totalXp: saved.totalXp,
        level: saved.level,
      },
    });

    try {
      const question = await getFirstQuestion(session?.courseId, session?.mode);
      dispatch({
        type: "QUESTION_LOADED",
        payload: { question },
      });
    } catch (error) {
      dispatch({
        type: "REQUEST_FAILED",
        payload: { message: error.message },
      });
    }
  }

  async function handleAnswer(answer, timedOut) {
    if (!gameState.currentQuestion || gameState.isLoading) {
      return;
    }

    dispatch({ type: "ANSWER_SUBMITTING" });

    const timeTakenMs = timedOut
      ? 15000
      : Date.now() - questionStartedAtRef.current;

    const payload = {
      question_id: gameState.currentQuestion.id,
      answer,
      tier: gameState.tier,
      correct_streak: gameState.correctStreak,
      wrong_streak: gameState.wrongStreak,
      total_xp: gameState.totalXp,
      time_taken_ms: timeTakenMs,
      mode: session?.mode || "mcq",
    };

    try {
      const result = await submitAnswer(payload);
      recordAnswer({
        mode: gameState.currentQuestion.mode,
        correct: result.correct,
        correctStreakAfter: result.correct_streak,
      });
      dispatch({
        type: "ANSWER_RESULT",
        payload: {
          ...result,
          time_taken_ms: timeTakenMs,
          gameComplete: gameState.questionCount + 1 >= QUEST_LENGTH,
        },
      });
    } catch (error) {
      dispatch({
        type: "REQUEST_FAILED",
        payload: { message: error.message },
      });
    }
  }

  // 1. Stage 1 & 2: FrontPage (Start, Course, Mode)
  let content;
  if (!session) {
    content = <FrontPage onLaunchSession={handleLaunchSession} />;
  } else if (!gameState.started) {
    // 2. Stage 3: Character Select
    content = (
      <>
        <WorldMotion />
        <CharacterSelect
          onSelect={startGame}
          loading={gameState.isLoading}
          onExit={handleExitToStart}
          courseTitle={session?.courseTitle}
        />
      </>
    );
  } else {
    // 3. Stage 4: Play Screen
    content = (
      <>
        <WorldMotion />
        <PlayScreen gameState={gameState} onAnswer={handleAnswer} onExit={handleExitToStart} />
      </>
    );
  }

  return (
    <>
      <ClickSound />
      <FullscreenToggle />
      <AchievementsToggle onClick={() => setShowAchievements(true)} />
      <OfflineToggle />
      {content}
      {showAchievements && <AchievementsPage onClose={() => setShowAchievements(false)} />}
    </>
  );
}
