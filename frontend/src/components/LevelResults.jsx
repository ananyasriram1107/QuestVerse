import { useEffect, useState } from "react";
import { getLevelResults } from "../api";

// Shown after a level is finished. Every number comes from the backend's
// record of the run (GET /levels/{id}/results) -- nothing is computed here.
export default function LevelResults({ levelId, sessionId, studentId, onContinue, onReview }) {
  const [load, setLoad] = useState({ status: "loading", data: null, error: null });

  const [reloadKey, setReloadKey] = useState(0);

  const fetchResults = () => {
    setLoad({ status: "loading", data: null, error: null });
    setReloadKey((key) => key + 1);
  };

  useEffect(() => {
    let cancelled = false;
    getLevelResults(levelId, studentId, sessionId)
      .then((data) => !cancelled && setLoad({ status: "ready", data, error: null }))
      .catch((error) => !cancelled && setLoad({ status: "error", data: null, error: error.message }));
    return () => {
      cancelled = true;
    };
  }, [levelId, studentId, sessionId, reloadKey]);

  if (load.status === "loading") {
    return (
      <main className="level-results level-results--status" role="status">
        Tallying your results…
      </main>
    );
  }

  if (load.status === "error") {
    return (
      <main className="level-results level-results--status" role="alert">
        <strong>Couldn't load your results</strong>
        <p>{load.error}</p>
        <div className="level-results__buttons">
          <button type="button" className="level-results__continue" onClick={fetchResults}>
            TRY AGAIN
          </button>
          <button type="button" className="stage-map__secondary" onClick={onContinue}>
            BACK TO THE MAP
          </button>
        </div>
      </main>
    );
  }

  const r = load.data;
  const unlocked = r.newly_unlocked[0];

  return (
    <main className="level-results">
      <section className="level-results__card">
        <h1 className="level-results__title">LEVEL COMPLETE!</h1>
        <h2 className="level-results__level">{r.level.name}</h2>
        <p className="level-results__count">{r.questions} questions</p>

        <div className="level-results__stars" role="img" aria-label={`${r.stars} of 3 stars`}>
          {[1, 2, 3].map((n) => (
            <span key={n} className={n <= r.stars ? "is-lit" : ""} style={{ "--i": n }} aria-hidden="true">
              ★
            </span>
          ))}
        </div>

        <dl className="level-results__stats">
          <div>
            <dd>{Math.round(r.first_try_pct)}%</dd>
            <dt>Accuracy</dt>
          </div>
          <div>
            <dd>{r.retries}</dd>
            <dt>Retries</dt>
          </div>
          <div>
            <dd className="level-results__xp">+{r.xp.earned_this_run}</dd>
            <dt>XP</dt>
          </div>
        </dl>

        {r.all_completed ? (
          <p className="level-results__win">★ Every level cleared! The treasure is yours.</p>
        ) : (
          unlocked && (
            <div className="level-results__unlocked" role="status">
              <span className="level-results__unlocked-icon" aria-hidden="true">🗝</span>
              <div>
                <small>{unlocked.new_stage ? "New Stage Unlocked" : "New Quest Unlocked"}</small>
                <strong>{unlocked.level_name}</strong>
              </div>
            </div>
          )
        )}

        <button type="button" className="level-results__continue" onClick={onContinue} autoFocus>
          {r.all_completed ? "Back to the Map" : "Continue Adventure"} <span aria-hidden="true">→</span>
        </button>

        {onReview && (
          <button type="button" className="level-results__review" onClick={() => onReview(r.session_id)}>
            Review Results
          </button>
        )}
      </section>
    </main>
  );
}
