const LEVEL_LABEL = { low: "Low", moderate: "Moderate", high: "High", insufficient_data: "Not enough data" };

// Compact, non-judgemental read-out of the backend's guessing-pattern estimate.
// Every word comes from analysis.summary (built server-side from the signals that
// actually fired); this only picks which analysis to show and lays it out.
// `overall` (all saved quests) is the fallback when one quest is too short to judge.
export default function GuessingPattern({ analysis, overall }) {
  const usingOverall = analysis?.status !== "ok" && overall?.status === "ok";
  const source = usingOverall ? overall : analysis ?? overall;
  const summary = source?.summary;
  if (!summary) return null;

  return (
    <section className="guess-pattern" aria-label="Guessing pattern">
      <h3 className="guess-pattern__title">
        Guessing Pattern
        <span className={`dash-badge dash-badge--${summary.level}`}>{LEVEL_LABEL[summary.level]}</span>
      </h3>
      <p className="guess-pattern__headline">{summary.headline}</p>
      <p className="guess-pattern__text">
        {summary.observation}
        {usingOverall && " (Looking across your recent quests.)"}
      </p>
      <p className="guess-pattern__next">
        <strong>Next step:</strong> {summary.next_step}
      </p>
      <small>An estimate from answer patterns, not a verdict.</small>
    </section>
  );
}
