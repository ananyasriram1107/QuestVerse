import { useEffect, useState } from "react";
import { getDashboard } from "../api";

const RISK_COPY = {
  low: {
    label: "Low",
    text: "Your first-try answers look like knowledge, not luck.",
  },
  moderate: {
    label: "Moderate",
    text: "Some of your first tries look like they could have been educated guesses. Worth slowing down on the ones you weren't sure about.",
  },
  high: {
    label: "High",
    text: "Your answer pattern is similar to what random picking would produce. That often just means the topic is new - it isn't a judgement about you.",
  },
};

const MODE_LABEL = { mcq: "multiple choice", short_answer: "short answer" };

function Stat({ label, value, hint }) {
  return (
    <div className="dash-stat">
      <dt>{label}</dt>
      <dd>{value}</dd>
      {hint && <small>{hint}</small>}
    </div>
  );
}

function pct(value) {
  return value === null || value === undefined ? "n/a" : `${Math.round(value)}%`;
}

export default function Dashboard({ sessionId, studentId, onPractice }) {
  const [state, setState] = useState({ loading: true, data: null, error: null });

  useEffect(() => {
    let cancelled = false;
    getDashboard(sessionId, studentId)
      .then((data) => !cancelled && setState({ loading: false, data, error: null }))
      .catch((error) => !cancelled && setState({ loading: false, data: null, error: error.message }));
    return () => {
      cancelled = true;
    };
  }, [sessionId, studentId]);

  if (state.loading) {
    return <p className="dash-note">Building your quest report…</p>;
  }
  if (state.error || !state.data) {
    return <p className="dash-note">Couldn't load the detailed report ({state.error}). Your results above are still saved.</p>;
  }

  const { completion, analysis, most_retried: mostRetried, topics, recommendations } = state.data;
  const ok = analysis.status === "ok";
  const m = analysis.metrics;
  const risk = ok ? analysis.risk : null;
  const chance = ok ? analysis.chance_baseline : null;

  return (
    <section className="dashboard" aria-label="Quest report">
      <h2 className="dashboard__title">Quest report</h2>

      <div className="dash-grid">
        <div className="dash-panel">
          <h3>Where you started</h3>
          <p className="dash-help">Your results before any hints or retries - the best picture of what you already knew.</p>
          {ok ? (
            <dl className="dash-stats">
              <Stat label="First-try accuracy" value={pct(m.first_attempt_accuracy_pct)} hint="Right on the first attempt" />
              <Stat label="Retry rate" value={pct(m.retry_rate_pct)} hint="Questions that needed another go" />
              <Stat label="Attempts / question" value={m.avg_attempts_per_question} hint="1.0 means no retries" />
            </dl>
          ) : (
            <p className="dash-note">{analysis.reason}</p>
          )}
        </div>

        <div className="dash-panel">
          <h3>Where you finished</h3>
          <p className="dash-help">
            Every question has to be solved to finish, so completion is always full - it isn't proof of mastery on its own.
          </p>
          <dl className="dash-stats">
            <Stat
              label="Completion"
              value={`${completion.solved}/${completion.quest_length}`}
              hint={completion.complete ? "All questions solved" : "Quest still in progress"}
            />
            <Stat
              label="Correction rate"
              value={ok ? pct(m.correction_rate_pct) : "n/a"}
              hint={ok && m.correction_rate_pct === null ? "No first-try misses to correct" : "Missed questions you later solved"}
            />
            <Stat label="XP earned" value={completion.xp_earned} />
          </dl>
        </div>
      </div>

      <div className="dash-panel">
        <h3>
          Guessing-pattern indicator
          {risk && <span className={`dash-badge dash-badge--${risk.level}`}>{RISK_COPY[risk.level].label}</span>}
        </h3>
        {ok ? (
          <>
            <p>{RISK_COPY[risk.level].text}</p>
            {chance.applicable && (
              <p className="dash-help">
                On multiple-choice first tries you got {chance.observed_correct} right; random picking would be expected to
                get about {chance.expected_correct_by_guessing}.
              </p>
            )}
            <p className="dash-help">
              This is an estimate from answer patterns, not a verdict. Repeated mistakes are usually a knowledge gap, and
              quick answers on their own never raise this indicator.
            </p>
            <details>
              <summary>How this was worked out</summary>
              <ul className="dash-list">
                {risk.signals.map((signal) => (
                  <li key={signal.id}>
                    <strong>{signal.points > 0 ? `+${signal.points}` : "0"}</strong> {signal.label}
                    <small> ({signal.rule})</small>
                  </li>
                ))}
              </ul>
              <p className="dash-help">
                Score {risk.score} of {risk.max_score}: 0-1 low, 2-3 moderate, 4+ high (high also needs two different signals).
              </p>
              {analysis.limitations.map((line) => (
                <p className="dash-help" key={line}>• {line}</p>
              ))}
            </details>
          </>
        ) : (
          <p className="dash-note">{analysis.reason} It appears once enough questions have been answered.</p>
        )}
      </div>

      <div className="dash-panel">
        <h3>Topic-wise performance</h3>
        <p className="dash-help">Across all your saved quests, grouped by course.</p>
        <ul className="dash-topics">
          {topics.map((topic) => (
            <li key={topic.topic}>
              <div className="dash-topics__row">
                <strong>{topic.topic.toUpperCase()}</strong>
                <span>
                  {topic.questions_attempted} questions · {pct(topic.first_attempt_accuracy_pct)} first try ·{" "}
                  {topic.avg_attempts_per_question} attempts each
                </span>
                {topic.needs_revision && <em className="dash-tag">Worth revisiting</em>}
                {!topic.enough_data && <em className="dash-tag dash-tag--muted">Not enough data yet</em>}
              </div>
              <div className="dash-bar" aria-hidden="true">
                <i style={{ width: `${topic.first_attempt_accuracy_pct ?? 0}%` }} />
              </div>
              <small>
                Typical first answer takes about {Math.round(topic.response_time.median_first_attempt_ms / 1000)}s
                {topic.response_time.median_when_first_wrong_ms !== null &&
                  topic.response_time.median_when_first_correct_ms !== null &&
                  `; misses took ${Math.round(topic.response_time.median_when_first_wrong_ms / 1000)}s vs ${Math.round(
                    topic.response_time.median_when_first_correct_ms / 1000
                  )}s for hits`}
                .
              </small>
            </li>
          ))}
        </ul>
      </div>

      <div className="dash-panel">
        <h3>Questions that took the most tries</h3>
        {mostRetried.length === 0 ? (
          <p className="dash-note">Nothing needed a retry this time.</p>
        ) : (
          <ol className="dash-list">
            {mostRetried.map((item) => (
              <li key={item.question_id}>
                {item.prompt} <small>- {item.retries} retr{item.retries === 1 ? "y" : "ies"}</small>
              </li>
            ))}
          </ol>
        )}
      </div>

      <div className="dash-panel">
        <h3>What to practise next</h3>
        {recommendations.length === 0 ? (
          <p className="dash-note">No suggestions yet - play a few more quests.</p>
        ) : (
          <ul className="dash-recs">
            {recommendations.map((rec) => (
              <li key={`${rec.courseId}-${rec.mode}`}>
                <p>{rec.reason}</p>
                <button type="button" className="dash-practice" onClick={() => onPractice?.(rec)}>
                  Practise {rec.title} ({MODE_LABEL[rec.mode] ?? rec.mode})
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <details className="dash-panel">
        <summary>What do these numbers mean?</summary>
        <dl className="dash-glossary">
          <dt>First-try accuracy</dt>
          <dd>Share of questions you got right on your first attempt.</dd>
          <dt>Retry rate</dt>
          <dd>Share of questions where you needed at least one more attempt.</dd>
          <dt>Attempts per question</dt>
          <dd>Total answers submitted divided by questions solved.</dd>
          <dt>Correction rate</dt>
          <dd>Of the questions you missed first, how many you went on to solve. Not applicable if you missed none.</dd>
          <dt>Guessing-pattern indicator</dt>
          <dd>How closely your answers resemble random picking. It is an estimate, and it can't tell why an answer was chosen.</dd>
        </dl>
      </details>
    </section>
  );
}
