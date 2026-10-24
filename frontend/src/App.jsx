import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import FrontPage from "./pages/Frontpage";
import StageMap from "./pages/StageMap";
import CharacterSelect from "./components/CharacterSelect";
import PlayScreen from "./components/PlayScreen";
import LevelResults from "./components/LevelResults";
import ReviewResults from "./components/ReviewResults";
import AuthScreen from "./components/AuthScreen";
import AccountMenu from "./components/AccountMenu";
import WeeklyReport from "./components/WeeklyReport";
import ClickSound from "./components/ClickSound";
import FullscreenToggle from "./components/FullscreenToggle";
import AchievementsToggle from "./components/AchievementsToggle";
import AchievementsPage from "./components/AchievementsPage";
import OfflineToggle from "./components/OfflineToggle";
import ErrorBoundary from "./components/ErrorBoundary";
import {
  completeLevel, fetchMe, getFirstQuestion, getProgress, getSession, getToken, logout, requestAiHint, setCurrentUser,
  startLevel, submitAnswer,
} from "./api";
import { gameReducer, initialGameState } from "./gameReducer";
import { navigate, useRoute } from "./route";
import { computeSessionStats } from "./utils/analytics";
import { recordCourseSession } from "./utils/progressStore";
import { loadCharacterProgress, saveCharacterProgress } from "./utils/characterStore";
import { loadStudentId, saveStudentId } from "./utils/studentStore";
import { recordAnswer, syncAchievementsWithServer } from "./utils/achievementStore";
import { scoped, setStorageScope } from "./utils/storageScope";
import { setOfflineMode } from "./utils/offlineMode";
import { getCharacter } from "./characters";
import "./App.css";

// Free play only: lets a refresh pick a course quest back up (level quizzes
// resume through their URL + the backend instead). Only the session id and the
// cosmetic identity are kept here -- the server owns the actual progress.
const RESUME_KEY = "questverse_active_session_v1";

function readResume() {
  try {
    return JSON.parse(sessionStorage.getItem(scoped(RESUME_KEY)));
  } catch {
    return null;
  }
}

function writeResume(value) {
  try {
    if (value) sessionStorage.setItem(scoped(RESUME_KEY), JSON.stringify(value));
    else sessionStorage.removeItem(scoped(RESUME_KEY));
  } catch {
    // storage unavailable -- resume just won't work
  }
}

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

function StatusScreen({ children }) {
  return (
    <main className="loading-screen" role="status">
      {children}
    </main>
  );
}

export default function App() {
  const route = useRoute();
  const [gameState, dispatch] = useReducer(gameReducer, initialGameState);
  const questionStartedAtRef = useRef(null);
  const [session, setSession] = useState(null); // free-play course/mode config (the pre-level flow)
  const [student, setStudent] = useState(null); // the chosen hero (character id); set once a user is signed in
  // Who is playing. Nothing but the login page shows until this is set.
  const [user, setUser] = useState(null);
  const [authStatus, setAuthStatus] = useState(() => (getToken() ? "checking" : "out"));
  const [authNotice, setAuthNotice] = useState(null);
  const [mapNotice, setMapNotice] = useState(null);
  const [showAchievements, setShowAchievements] = useState(false);
  // ack: the final answer's feedback popup has been dismissed, so results may show.
  const [finish, setFinish] = useState({ attempt: 0, error: null, ack: false });
  const progressRecordedRef = useRef(false);
  const completionHandledRef = useRef(null);
  const openingLevelRef = useRef(null);

  // ---- Accounts ----
  const signIn = useCallback((signedInUser) => {
    setCurrentUser(signedInUser.id);
    setStorageScope(signedInUser.id);
    setOfflineMode(false);                // an account needs the server; the Offline toggle can switch it back on
    setUser(signedInUser);
    setStudent(loadStudentId());          // this user's last hero, if they have played before
    setAuthNotice(null);
    setAuthStatus("in");
    syncAchievementsWithServer();
  }, []);

  // No account: Free Play runs on the in-browser engine, which needs no server at all.
  const signInGuest = useCallback(() => {
    setCurrentUser(null);
    setStorageScope(null);
    setOfflineMode(true);
    setUser({ id: null, username: "Guest", guest: true });
    setStudent(loadStudentId());
    setAuthNotice(null);
    setAuthStatus("in");
  }, []);

  // A saved login is checked once at start-up.
  useEffect(() => {
    if (!getToken()) return undefined;
    let cancelled = false;
    fetchMe()
      .then((me) => {
        if (cancelled) return;
        if (me) signIn(me);
        else setAuthStatus("out");
      })
      .catch((error) => {
        if (cancelled) return;
        setAuthNotice(error.message);
        setAuthStatus("out");
      });
    return () => {
      cancelled = true;
    };
  }, [signIn]);

  // The session ended (logout button, or the server said the token is no longer valid):
  // drop everything that belonged to that user and go back to the login page.
  useEffect(() => {
    const onLogout = () => {
      setCurrentUser(null);
      setStorageScope(null);
      progressRecordedRef.current = false;
      dispatch({ type: "RESET_GAME" });
      setSession(null);
      setStudent(null);
      setUser(null);
      setShowAchievements(false);
      setMapNotice(null);
      setAuthStatus("out");
      navigate({ name: "title" }, { replace: true });
    };
    window.addEventListener("questverse:logout", onLogout);
    return () => window.removeEventListener("questverse:logout", onLogout);
  }, []);

  async function handleLogout() {
    if (!user?.guest) await logout();
    window.dispatchEvent(new Event("questverse:logout"));
  }

  // Achievements is an overlay over the current screen (which stays mounted, so
  // the map, XP and quest state are untouched). It gets its own history entry so
  // the browser Back button closes it instead of leaving the app.
  function openAchievements() {
    window.history.pushState({ achievements: true }, "", window.location.href);
    setShowAchievements(true);
  }

  function closeAchievements() {
    if (window.history.state?.achievements) window.history.back();
    else setShowAchievements(false);
  }

  useEffect(() => {
    if (!showAchievements) return undefined;
    const onPop = () => setShowAchievements(false);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [showAchievements]);

  // Free play: resume an in-progress course quest after a refresh.
  useEffect(() => {
    if (!user) return undefined;
    const saved = readResume();
    if (!saved?.sessionId) return undefined;
    let cancelled = false;
    getSession(saved.sessionId, saved.identity?.characterId).then((snap) => {
      if (cancelled) return;
      if (!snap) {
        writeResume(null);
        return;
      }
      progressRecordedRef.current = snap.game_complete;
      setSession(saved.session);
      dispatch({ type: "RESUME_SESSION", payload: { ...snap, identity: saved.identity } });
    });
    return () => {
      cancelled = true;
    };
  }, [user]);

  useEffect(() => {
    if (gameState.currentQuestion?.id) {
      questionStartedAtRef.current = Date.now();
    }
  }, [gameState.currentQuestion?.id, gameState.attemptCount]);

  useEffect(() => {
    if (gameState.gameComplete && !progressRecordedRef.current && gameState.courseId) {
      progressRecordedRef.current = true;
      recordCourseSession(gameState.courseId, computeSessionStats(gameState.attempts));
    }
  }, [gameState.gameComplete, gameState.courseId, gameState.attempts]);

  // Keeps the active character's local save (XP/level) up to date for the
  // free-play flow. Level progress and XP live on the backend, not here.
  useEffect(() => {
    if (gameState.started && gameState.characterId) {
      saveCharacterProgress(gameState.characterId, {
        totalXp: gameState.totalXp,
        level: gameState.level,
      });
    }
  }, [gameState.started, gameState.characterId, gameState.totalXp, gameState.level]);

  // Screens that need a hero send you to pick one first.
  useEffect(() => {
    if (user && !student && !session && ["map", "play", "results", "review"].includes(route.name)) {
      navigate({ name: "hero" }, { replace: true });
    }
  }, [user, student, session, route.name]);

  // Leaving the quiz screens drops the in-memory quiz; the backend still holds
  // the run, so coming back (or pressing Back/Forward) resumes it.
  useEffect(() => {
    if (!session && gameState.levelId && ["map", "title", "hero", "free", "upload"].includes(route.name)) {
      progressRecordedRef.current = false;
      dispatch({ type: "RESET_GAME" });
    }
  }, [session, gameState.levelId, route.name]);

  async function openLevel(levelId, { resumeOnly = false } = {}) {
    if (!student || openingLevelRef.current === levelId) {
      return;
    }
    openingLevelRef.current = levelId;
    try {
      const snap = await startLevel(levelId, student, resumeOnly);
      setMapNotice(null);
      progressRecordedRef.current = false;
      completionHandledRef.current = null;
      setFinish({ attempt: 0, error: null, ack: false });
      dispatch({
        type: "RESUME_SESSION",
        payload: {
          ...snap,
          identity: {
            name: getCharacter(student).label,
            characterId: student,
            courseId: snap.level_info.course_id,
            courseTitle: snap.level_info.name,
            mode: snap.mode,
            levelId,
          },
        },
      });
      navigate({ name: "play", levelId });
    } catch (error) {
      setMapNotice(error.message);
      navigate({ name: "map" }, { replace: true });
    } finally {
      openingLevelRef.current = null;
    }
  }

  // URL-driven entry to a quiz (refresh, Back/Forward): resume what the backend
  // has for this level -- never start a fresh run from a URL alone.
  useEffect(() => {
    if (session || route.name !== "play" || !student) return;
    const alreadyLoaded = gameState.started && gameState.levelId === route.levelId && !gameState.gameComplete;
    if (!alreadyLoaded) {
      // Deferred a tick: openLevel updates several pieces of state once the
      // backend answers, which must not happen synchronously inside this effect.
      queueMicrotask(() => openLevel(route.levelId, { resumeOnly: true }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route.name, route.levelId, student, session]);

  // The final correct answer completes the level on the server; confirm it
  // (idempotent), then show the results in place of the finished quiz.
  useEffect(() => {
    if (!gameState.gameComplete || !gameState.levelId || !gameState.sessionId || !finish.ack) return;
    if (completionHandledRef.current === `${gameState.sessionId}:${finish.attempt}`) return;
    completionHandledRef.current = `${gameState.sessionId}:${finish.attempt}`;
    const { levelId, sessionId } = gameState;
    completeLevel(levelId, student, sessionId)
      .then(() => navigate({ name: "results", levelId, sessionId }, { replace: true }))
      .catch((error) => setFinish((previous) => ({ ...previous, error: error.message })));
  }, [gameState, student, finish.attempt, finish.ack]);

  function chooseHero(character) {
    saveStudentId(character.id);
    setStudent(character.id);
    setMapNotice(null);
    navigate({ name: "map" });
  }

  function handleLaunchSession(config) {
    setSession(config);
  }

  // Back to the map from any quiz screen. An unfinished level run stays on the
  // server, so the map shows it as in progress and the level resumes.
  function exitToMap() {
    progressRecordedRef.current = false;
    writeResume(null);
    dispatch({ type: "RESET_GAME" });
    setSession(null);
    navigate({ name: "map" });
  }

  // From a quest report: open a real level for the recommended course.
  async function handlePractice(rec) {
    try {
      const progress = await getProgress(student);
      const open = progress.stages
        .flatMap((stage) => stage.levels)
        .filter((level) => level.course_id === rec.courseId && level.state !== "locked");
      const pick = open.find((level) => level.state !== "completed") ?? open[0];
      if (pick) {
        dispatch({ type: "RESET_GAME" });
        setSession(null);
        await openLevel(pick.id);
      } else {
        setMapNotice(`No open level for ${rec.title} yet. Keep going to unlock more.`);
        exitToMap();
      }
    } catch (error) {
      setMapNotice(error.message);
      exitToMap();
    }
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
      const question = await getFirstQuestion(session?.courseId, session?.mode, saved.totalXp, character.id);
      dispatch({
        type: "QUESTION_LOADED",
        payload: { question, sessionId: question.session_id, questLength: question.quest_length },
      });
      if (question.session_id) {
        writeResume({
          sessionId: question.session_id,
          session,
          identity: {
            name: character.label,
            characterId: character.id,
            courseId: session?.courseId,
            courseTitle: session?.courseTitle,
            mode: session?.mode,
          },
        });
      }
    } catch (error) {
      dispatch({
        type: "REQUEST_FAILED",
        payload: { message: error.message },
      });
    }
  }

  // Resolves to the hint text; PlayScreen owns the loading/error display.
  function handleRequestHint() {
    return requestAiHint({
      session_id: gameState.sessionId,
      student_id: gameState.characterId,
      question_id: gameState.currentQuestion.id,
    });
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
      session_id: gameState.sessionId,
      student_id: gameState.characterId,
      question_id: gameState.currentQuestion.id,
      answer,
      tier: gameState.tier,
      correct_streak: gameState.correctStreak,
      wrong_streak: gameState.wrongStreak,
      total_xp: gameState.totalXp,
      time_taken_ms: timeTakenMs,
      mode: session?.mode || gameState.mode || "mcq",
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
        },
      });
    } catch (error) {
      dispatch({
        type: "REQUEST_FAILED",
        payload: { message: error.message },
      });
    }
  }

  function acknowledgeFinish() {
    setFinish((previous) => (previous.ack ? previous : { ...previous, ack: true }));
  }

  function retryFinish() {
    setFinish((previous) => ({ ...previous, attempt: previous.attempt + 1, error: null }));
  }

  // Free play (course picker -> character -> quest) keeps working as before.
  let content;
  if (session) {
    if (!gameState.started) {
      content = (
        <>
          <WorldMotion />
          <CharacterSelect
            onSelect={startGame}
            loading={gameState.isLoading}
            onExit={exitToMap}
            courseTitle={session?.courseTitle}
          />
        </>
      );
    } else {
      content = (
        <>
          <WorldMotion />
          <PlayScreen gameState={gameState} onAnswer={handleAnswer} onExit={exitToMap} onPractice={handlePractice} onRequestHint={handleRequestHint} />
        </>
      );
    }
  } else {
    switch (route.name) {
      case "hero":
        content = (
          <>
            <WorldMotion />
            <CharacterSelect
              onSelect={chooseHero}
              loading={false}
              onExit={() => navigate(student ? { name: "map" } : { name: "title" })}
              courseTitle="Choose your hero"
              showLevelProgress
            />
          </>
        );
        break;

      case "map":
        content = student && (
          <>
            <WorldMotion />
            <StageMap
              key={student}
              studentId={student}
              notice={mapNotice}
              onOpenLevel={(levelId) => openLevel(levelId)}
              onFreePlay={() => navigate({ name: "free" })}
              onUpload={() => navigate({ name: "upload" })}
              onBack={() => navigate({ name: "title" })}
              onSwitchHero={() => navigate({ name: "hero" })}
            />
          </>
        );
        break;

      case "play":
        if (gameState.started && gameState.levelId === route.levelId) {
          content = gameState.gameComplete && finish.ack ? (
            <StatusScreen>
              {finish.error ? (
                <>
                  <p>Couldn't record your results: {finish.error}</p>
                  <button type="button" className="stage-map__continue" onClick={retryFinish}>
                    TRY AGAIN
                  </button>
                </>
              ) : (
                "Recording your results…"
              )}
            </StatusScreen>
          ) : (
            <>
              <WorldMotion />
              <PlayScreen
                gameState={gameState}
                onAnswer={handleAnswer}
                onExit={exitToMap}
                onPractice={handlePractice}
                onRequestHint={handleRequestHint}
                onLevelDone={acknowledgeFinish}
              />
            </>
          );
        } else {
          content = (
            <>
              <WorldMotion />
              <StatusScreen>Opening your level…</StatusScreen>
            </>
          );
        }
        break;

      case "results":
        content = student && (
          <>
            <WorldMotion />
            <LevelResults
              key={`${route.levelId}:${route.sessionId}`}
              levelId={route.levelId}
              sessionId={route.sessionId}
              studentId={student}
              onContinue={() => navigate({ name: "map" })}
              onReview={(reviewSessionId) => navigate({ name: "review", levelId: route.levelId, sessionId: reviewSessionId })}
              onPractice={handlePractice}
            />
          </>
        );
        break;

      case "review":
        content = student && (
          <>
            <WorldMotion />
            <ReviewResults
              key={`${route.levelId}:${route.sessionId}`}
              levelId={route.levelId}
              sessionId={route.sessionId}
              studentId={student}
              onBack={() => navigate({ name: "results", levelId: route.levelId, sessionId: route.sessionId })}
            />
          </>
        );
        break;

      case "report":
        content = <WeeklyReport onBack={() => navigate(student ? { name: "map" } : { name: "title" })} />;
        break;

      case "free":
      case "upload":
        content = (
          <FrontPage
            key={route.name}
            initialStage={route.name === "upload" ? "upload" : "courses"}
            onLaunchSession={handleLaunchSession}
            onOpenMap={() => navigate({ name: "hero" })}
            onBackToMap={() => navigate(student ? { name: "map" } : { name: "title" })}
          />
        );
        break;

      default:
        content = (
          <FrontPage
            key="title"
            initialStage="start"
            onLaunchSession={handleLaunchSession}
            onOpenMap={() => navigate({ name: "hero" })}
          />
        );
    }
  }

  if (authStatus === "checking") {
    return <StatusScreen>Checking your login…</StatusScreen>;
  }
  if (!user) {
    return (
      <>
        <ClickSound />
        <WorldMotion />
        <AuthScreen onAuthed={signIn} onGuest={signInGuest} notice={authNotice} />
      </>
    );
  }

  return (
    <>
      <ClickSound />
      <FullscreenToggle />
      <AchievementsToggle onClick={openAchievements} />
      <AccountMenu user={user} onReport={() => navigate({ name: "report" })} onLogout={handleLogout} />
      <OfflineToggle />
      <ErrorBoundary key={route.name}>{content}</ErrorBoundary>
      {showAchievements && <AchievementsPage onClose={closeAchievements} />}
    </>
  );
}
