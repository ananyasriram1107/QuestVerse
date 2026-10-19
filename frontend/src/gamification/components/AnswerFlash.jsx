import mascotWrong from "../../assets/mascot-wrong.png";

export default function AnswerFlash({ phase, score = 0, feedback, xp = 10, onDismiss }) {
  if (!phase) {
    return null;
  }

  if (phase === "xpboost") {
    return (
      <div className="answer-flash answer-flash--xpboost" role="status">
        <div className="answer-flash__panel answer-flash__panel--xpboost">
          <div className="answer-flash__stars" aria-hidden="true">
            <i /><i /><i /><i /><i /><i /><i /><i />
          </div>
          <div className="xpboost-card">
            <strong className="pixel-gold-text">XP BOOST!</strong>
            <div className="xpboost-coins" aria-hidden="true">
              <i /><i /><i /><i /><i />
            </div>
            <em>+{xp} XP</em>
          </div>
        </div>
      </div>
    );
  }

  const correct = phase === "win";

  return (
    <div
      className={correct ? "answer-flash answer-flash--correct" : "answer-flash answer-flash--wrong"}
      role="status"
    >
      <div className="answer-flash__panel">
        <div className="pixel-hud pixel-hud--score" aria-hidden="true">
          <span>SCORE</span>
          <strong>{score}</strong>
        </div>

        {correct && <div className="answer-flash__stars" aria-hidden="true">
          <i /><i /><i /><i /><i /><i /><i /><i />
        </div>}

        <div className="answer-flash__content">
          <strong className={correct ? "pixel-gold-text" : "pixel-red-text"}>
            {correct ? "YOU WIN!" : "TRY AGAIN!"}
          </strong>

          {feedback && <p className="answer-flash__feedback">{feedback}</p>}

          <button type="button" className="answer-flash__ok" onClick={onDismiss}>
            OK
          </button>
        </div>

        {!correct && (
          <img
            className="answer-flash__mascot"
            src={mascotWrong}
            alt=""
            aria-hidden="true"
          />
        )}
      </div>
    </div>
  );
}
