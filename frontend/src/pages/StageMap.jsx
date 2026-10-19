import { useEffect, useMemo, useState } from "react";
import XPBar from "../gamification/components/XPBar";
import { xpProgress } from "../gamification/gamification";
import { getCharacter } from "../characters";
import { getProgress } from "../api";
import { computeLayout, pathThrough } from "../mapLayout";

const STATE_LABEL = { locked: "LOCKED", available: "NEW", in_progress: "RESUME", completed: "CLEARED" };
const STATE_ICON = { locked: "🔒", available: "▶", in_progress: "…", completed: "★" };

function Sprite({ character }) {
  return character.spriteType === "image" ? (
    <img className="stage-map__sprite" src={character.spriteSrc} alt="" />
  ) : (
    <span className="stage-map__sprite stage-map__sprite--emoji">{character.spriteValue}</span>
  );
}

function stars(count) {
  return "★".repeat(count) + "☆".repeat(3 - count);
}

// The adventure map. It owns no progression logic: it asks the backend
// (GET /progress/me) for every stage/level state on each visit and draws it.
export default function StageMap({ studentId, notice, onOpenLevel, onFreePlay, onUpload, onBack, onSwitchHero }) {
  const [load, setLoad] = useState({ status: "loading", data: null, error: null });

  const [reloadKey, setReloadKey] = useState(0);

  const fetchProgress = () => {
    setLoad((previous) => ({ ...previous, status: "loading", error: null }));
    setReloadKey((key) => key + 1);
  };

  useEffect(() => {
    let cancelled = false;
    getProgress(studentId)
      .then((data) => !cancelled && setLoad({ status: "ready", data, error: null }))
      .catch((error) => !cancelled && setLoad({ status: "error", data: null, error: error.message }));
    return () => {
      cancelled = true;
    };
  }, [studentId, reloadKey]);

  const character = getCharacter(studentId);
  const data = load.data;
  const layout = useMemo(() => (data ? computeLayout(data.stages) : null), [data]);

  const header = (
    <header className="stage-map__header">
      <button type="button" className="pixel-back stage-map__back" onClick={onBack}>
        ◀ TITLE
      </button>

      <div className="stage-map__title">
        <span className="stage-map__eyebrow">★ {data?.world?.name?.toUpperCase() ?? "QUESTVERSE"} ★</span>
        <h1 className="pixel-gold-text pixel-gold-text--md">CHOOSE YOUR ADVENTURE</h1>
      </div>

      <div className="stage-map__hud">
        <div className="stage-map__player">
          <div className="stage-map__avatar" aria-hidden="true">
            <Sprite character={character} />
          </div>
          <div className="stage-map__player-info">
            <span className="stage-map__eyebrow">{character.label}</span>
            <XPBar xp={data?.total_xp ?? 0} level={data?.level ?? 1} progressPercent={xpProgress(data?.total_xp ?? 0)} />
          </div>
          <button type="button" className="stage-map__switch" onClick={onSwitchHero}>
            SWITCH
          </button>
        </div>

        <div
          className="stage-map__progress"
          aria-label={data ? `${data.totals.levels_completed} of ${data.totals.levels_total} levels cleared` : "Loading progress"}
        >
          <div className="stage-map__progress-head">
            <strong>{data ? `${data.totals.levels_completed}/${data.totals.levels_total}` : "–"}</strong>
            <span>LEVELS CLEARED</span>
          </div>
          <div className="stage-map__bar" aria-hidden="true">
            <i style={{ width: data ? `${(data.totals.levels_completed / Math.max(1, data.totals.levels_total)) * 100}%` : "0%" }} />
          </div>
          <small>
            {data
              ? `${data.stages.filter((stage) => stage.state === "completed").length}/${data.stages.length} stages · ${data.totals.quests_completed} quest${data.totals.quests_completed === 1 ? "" : "s"} completed`
              : "…"}
          </small>
        </div>
      </div>
    </header>
  );

  if (load.status === "loading" && !data) {
    return (
      <div className="stage-map-page">
        {header}
        <p className="stage-map__status" role="status">Loading your adventure…</p>
      </div>
    );
  }

  if (load.status === "error") {
    return (
      <div className="stage-map-page">
        {header}
        <div className="stage-map__status stage-map__status--error" role="alert">
          <strong>Couldn't load the map</strong>
          <p>{load.error}</p>
          <div className="stage-map__actions">
            <button type="button" className="stage-map__continue" onClick={fetchProgress}>
              TRY AGAIN
            </button>
            <button type="button" className="stage-map__secondary" onClick={onFreePlay}>
              FREE PLAY
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!layout || layout.nodes.length === 0) {
    return (
      <div className="stage-map-page">
        {header}
        <p className="stage-map__status">No levels are available yet.</p>
      </div>
    );
  }

  const currentId = data.current_level_id;
  const currentNode = layout.nodes.find((node) => node.level.id === currentId) ?? null;
  const currentIndex = currentNode ? layout.nodes.indexOf(currentNode) : layout.nodes.length;
  const points = layout.nodes.map((node) => [node.x, node.y]);
  const fullPath = pathThrough([...points, layout.chest]);
  const walkedPath = currentIndex > 0 ? pathThrough(points.slice(0, Math.min(currentIndex + 1, points.length))) : "";
  const [markerX, markerY] = currentNode ? [currentNode.x, currentNode.y] : layout.chest;
  const toPct = (y) => `${(y * 100) / layout.height}%`;
  const firstLevelId = layout.nodes[0].level.id;
  const nextLevel = currentNode?.level;

  const continueLabel = data.all_completed
    ? "REPLAY FROM THE START"
    : data.totals.levels_completed === 0 && nextLevel?.state !== "in_progress"
      ? "BEGIN ADVENTURE"
      : "CONTINUE ADVENTURE";

  return (
    <div className="stage-map-page">
      {header}

      {notice && (
        <p className="stage-map__notice" role="alert">
          {notice}
        </p>
      )}

      {data.all_completed && (
        <p className="stage-map__notice stage-map__notice--win" role="status">
          ★ Every level cleared! The treasure is yours. Pick any level to revisit it.
        </p>
      )}

      <div className="stage-map__actions">
        <button type="button" className="stage-map__continue" onClick={() => onOpenLevel(currentId ?? firstLevelId)}>
          {continueLabel} <span aria-hidden="true">▶</span>
        </button>
        <button type="button" className="stage-map__secondary" onClick={onFreePlay}>
          FREE PLAY
        </button>
        <button type="button" className="stage-map__secondary" onClick={onUpload}>
          ⬆ UPLOAD PDF
        </button>
      </div>
      {nextLevel && (
        <p className="stage-map__next">
          Next: <strong>{nextLevel.name}</strong>
        </p>
      )}

      <section className="stage-map" style={{ "--map-ratio": `100 / ${layout.height}` }} aria-label="Adventure map">
        {layout.bands.map(({ stage, top, height }) => (
          <div
            key={stage.id}
            className={`stage-region stage-region--${stage.theme}${stage.state === "locked" ? " is-locked" : ""}`}
            style={{ top: toPct(top), height: toPct(height) }}
          >
            <div className="stage-region__banner">
              <span>{stage.state === "locked" ? "LOCKED" : stage.state === "completed" ? "CLEARED" : "STAGE"}{stage.difficulty ? ` · ${stage.difficulty.toUpperCase()}` : ""}</span>
              <strong>{stage.name}</strong>
              <em>{stage.description}</em>
              <small>
                {stage.levels_completed}/{stage.levels_total} levels cleared
              </small>
            </div>
          </div>
        ))}

        <svg className="stage-map__path" viewBox={`0 0 100 ${layout.height}`} preserveAspectRatio="none" aria-hidden="true">
          <path d={fullPath} className="stage-map__road stage-map__road--under" vectorEffect="non-scaling-stroke" />
          <path d={fullPath} className="stage-map__road" vectorEffect="non-scaling-stroke" />
          {walkedPath && <path d={walkedPath} className="stage-map__road stage-map__road--walked" vectorEffect="non-scaling-stroke" />}
        </svg>

        {layout.nodes.map((node, index) => {
          const { level } = node;
          const locked = level.state === "locked";
          const isCurrent = level.id === currentId;
          const previous = layout.nodes[index - 1]?.level;
          const [course, ...rest] = level.name.split(": ");
          const subtitle = rest.join(": ");
          return (
            <button
              key={level.id}
              type="button"
              className={`stage-node stage-node--${level.state}${isCurrent ? " is-current" : ""}`}
              style={{ left: `${node.x}%`, top: toPct(node.y) }}
              disabled={locked}
              onClick={() => onOpenLevel(level.id)}
              aria-label={`${level.name}, ${node.stage.name}: ${STATE_LABEL[level.state].toLowerCase()}${
                level.stars ? `, ${level.stars} of 3 stars` : ""
              }${locked && previous ? `. Complete ${previous.name} to unlock.` : ""}`}
              aria-current={isCurrent ? "step" : undefined}
              title={locked ? "Locked: finish the earlier levels first" : level.description}
            >
              <span className="stage-node__disc">
                <span className="stage-node__icon">{STATE_ICON[level.state]}</span>
              </span>
              <span className="stage-node__label">
                <strong>{level.number ? `${level.number}. ` : ""}{course}</strong>
                <small>
                  {node.stage.difficulty ? `${node.stage.difficulty} · ` : ""}{subtitle}
                  {level.state === "completed" ? ` · ${stars(level.stars)}` : ""}
                </small>
                <small>{level.state === "completed" ? "REPLAY" : STATE_LABEL[level.state]}</small>
              </span>
            </button>
          );
        })}

        <div
          className={`stage-map__player-marker stage-map__player-marker--${markerX < 50 ? "right" : "left"}`}
          style={{ left: `${markerX}%`, top: toPct(markerY) }}
          aria-hidden="true"
        >
          <span className="stage-map__here">{currentNode ? "YOU ARE HERE" : "TREASURE!"}</span>
          <Sprite character={character} />
        </div>

        <div
          className={`stage-map__chest treasure-chest${data.all_completed ? " treasure-chest--open" : ""}`}
          style={{ left: `${layout.chest[0]}%`, top: toPct(layout.chest[1]) }}
          role="img"
          aria-label={data.all_completed ? "Treasure unlocked" : "Treasure at the end of the road"}
        >
          <span className="treasure-chest__lid" />
          <span className="treasure-chest__base" />
          {data.all_completed && <span className="treasure-chest__glow" aria-hidden="true" />}
        </div>
      </section>
    </div>
  );
}
