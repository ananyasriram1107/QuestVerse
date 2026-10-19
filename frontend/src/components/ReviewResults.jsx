import { useEffect, useState } from "react";
import { getDashboard, getLevelResults } from "../api";
import GuessingPattern from "./GuessingPattern";

// "Review Results": the detail screen behind the level victory screen. Deliberately
// small -- the level recap plus the compact Guessing Pattern read-out, no dashboard.
export default function ReviewResults({ levelId, sessionId, studentId, onBack }) {
  const [state, setState] = useState({ status: "loading", level: null, report: null, error: null });

  useEffect(() => {
    let cancelled = false;
    Promise.all([getLevelResults(levelId, studentId, sessionId), getDashboard(sessionId, studentId)])
      .then(([results, report]) => !cancelled && setState({ status: "ready", level: results, report, error: null }))
      .catch((error) => !cancelled && setState({ status: "error", level: null, report: null, error: error.message }));
    return () => {
      cancelled = true;
    };
  }, [levelId, sessionId, studentId]);

  return (
    <main className="level-results">
      <section className="level-results__card review-results">
        <button type="button" className="achievements-page__back" onClick={onBack}>
          ← Back
        </button>
        <h1 className="review-results__title">REVIEW RESULTS</h1>

        {state.status === "loading" && <p role="status">Reading your quest log…</p>}
        {state.status === "error" && <p role="alert">Couldn't load the review: {state.error}</p>}
        {state.status === "ready" && (
          <>
            <h2 className="level-results__level">{state.level.level.name}</h2>
            <p className="level-results__count">{state.level.questions} questions answered</p>
            <GuessingPattern analysis={state.report.analysis} overall={state.report.analysis_overall} />
          </>
        )}
      </section>
    </main>
  );
}
