import { useEffect, useState } from "react";
import { ACHIEVEMENTS } from "../achievements";
import { getCharacter } from "../characters";
import { getWeeklyReport, updateEmail } from "../api";

const fmtDay = (iso) => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });

function weekLabel(startIso) {
  const start = new Date(startIso);
  const end = new Date(start.getTime() + 6 * 86400000);
  return `${fmtDay(start)} – ${fmtDay(end)}`;
}

function Bars({ rows }) {
  return (
    <ul className="report-bars">
      {rows.map(([name, entry]) => (
        <li key={name}>
          <span>{name}</span>
          <div className="report-bars__track" aria-hidden="true">
            <i style={{ width: `${entry.first_try_accuracy_pct ?? 0}%` }} />
          </div>
          <strong>{Math.round(entry.first_try_accuracy_pct ?? 0)}%</strong>
          <small>{entry.questions} q</small>
        </li>
      ))}
    </ul>
  );
}

// The player's weekly progress, read from what the server has recorded (attempts, levels, XP,
// achievements). Past weeks are stored by the server and don't change once the week is over.
export default function WeeklyReport({ onBack }) {
  const [week, setWeek] = useState(null);
  const [load, setLoad] = useState({ status: "loading", data: null, error: null });
  const [email, setEmail] = useState("");
  const [emailState, setEmailState] = useState({ busy: false, message: null });

  useEffect(() => {
    let cancelled = false;
    getWeeklyReport(week)
      .then((data) => {
        if (cancelled) return;
        setLoad({ status: "ready", data, error: null });
        setEmail((current) => current || data.email || "");
      })
      .catch((error) => !cancelled && setLoad({ status: "error", data: null, error: error.message }));
    return () => {
      cancelled = true;
    };
  }, [week]);

  async function saveEmail(event) {
    event.preventDefault();
    setEmailState({ busy: true, message: null });
    try {
      const result = await updateEmail(email.trim() || null);
      setEmailState({
        busy: false,
        message: result.email
          ? result.email_delivery
            ? "Saved - your weekly update will be emailed to you."
            : "Saved. Emailing isn't switched on for this server yet, but your report is always here."
          : "Email removed.",
      });
    } catch (error) {
      setEmailState({ busy: false, message: error.message });
    }
  }

  const report = load.data?.report;
  const delta = report?.accuracy_change_pts;

  return (
    <main className="level-results">
      <section className="level-results__card review-results weekly-report">
        <button type="button" className="achievements-page__back" onClick={onBack}>
          ← Back
        </button>
        <h1 className="review-results__title">WEEKLY REPORT</h1>

        {load.status === "loading" && <p role="status">Gathering your week…</p>}
        {load.status === "error" && <p role="alert">Couldn't load your report: {load.error}</p>}

        {load.status === "ready" && report && (
          <>
            <label className="weekly-report__week">
              Week
              <select value={report.week_start} onChange={(event) => setWeek(event.target.value)}>
                {load.data.weeks.map((w) => (
                  <option key={w} value={w}>
                    {weekLabel(w)}
                    {w === load.data.weeks[0] ? " (this week)" : ""}
                  </option>
                ))}
              </select>
            </label>

            <dl className="level-results__stats weekly-report__stats">
              <div>
                <dd>{report.questions_answered}</dd>
                <dt>Questions</dt>
              </div>
              <div>
                <dd>{report.first_try_accuracy_pct === null ? "–" : `${Math.round(report.first_try_accuracy_pct)}%`}</dd>
                <dt>First-try accuracy</dt>
              </div>
              <div>
                <dd className="level-results__xp">+{report.xp_earned}</dd>
                <dt>XP</dt>
              </div>
              <div>
                <dd>{report.levels_completed.length}</dd>
                <dt>Levels cleared</dt>
              </div>
            </dl>
            {delta !== null && Math.abs(delta) >= 1 && (
              <p className="weekly-report__delta">
                {delta > 0 ? "▲" : "▼"} {Math.abs(Math.round(delta))} points vs last week
              </p>
            )}

            <ul className="weekly-report__highlights">
              {report.highlights.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>

            {Object.keys(report.heroes).length > 0 && (
              <section>
                <h3>By hero</h3>
                <Bars rows={Object.entries(report.heroes).map(([id, e]) => [getCharacter(id).label, e])} />
              </section>
            )}
            {Object.keys(report.topics).length > 0 && (
              <section>
                <h3>By topic</h3>
                <Bars rows={Object.entries(report.topics).map(([id, e]) => [id.toUpperCase(), e])} />
              </section>
            )}

            {report.achievements_unlocked.length > 0 && (
              <section>
                <h3>Achievements unlocked</h3>
                <p className="weekly-report__badges">
                  {report.achievements_unlocked.map((u) => {
                    const a = ACHIEVEMENTS.find((x) => x.id === u.id);
                    return (
                      <span key={u.id} title={a?.description}>
                        {a?.icon ?? "🏅"} {a?.label ?? u.id}
                      </span>
                    );
                  })}
                </p>
              </section>
            )}

            <p className="weekly-report__guess">
              <strong>Guessing pattern:</strong> {report.guessing_pattern.headline} {report.guessing_pattern.next_step}
            </p>

            <form className="weekly-report__email" onSubmit={saveEmail}>
              <label>
                Email me this report every week
                <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" />
              </label>
              <button type="submit" disabled={emailState.busy}>
                Save
              </button>
              {emailState.message && <small role="status">{emailState.message}</small>}
            </form>
          </>
        )}
      </section>
    </main>
  );
}
