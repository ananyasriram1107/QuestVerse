import { useState } from "react";
import { generateQuestionsFromPdf } from "../api";
import { isOfflineMode } from "../utils/offlineMode";

const MODES = [
  { id: "mcq", label: "Multiple Choice" },
  { id: "short_answer", label: "Short Answer" },
];

const COUNT_OPTIONS = [3, 5, 10];

export default function PdfUploadStage({ onBack, onLaunch }) {
  const [file, setFile] = useState(null);
  const [mode, setMode] = useState("mcq");
  const [count, setCount] = useState(5);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const offline = isOfflineMode();

  async function handleSubmit(event) {
    event.preventDefault();

    if (!file || loading || offline) {
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const result = await generateQuestionsFromPdf(file, mode, count);
      onLaunch({
        courseId: result.courseId,
        courseTitle: file.name.replace(/\.pdf$/i, ""),
        mode: result.mode,
      });
    } catch (err) {
      setError(err.message || "Something went wrong generating questions.");
      setLoading(false);
    }
  }

  return (
    <section className="selection-screen">
      <div className="selection-heading">
        <div>
          <div className="pixel-small-title">STEP 01</div>
          <h2 className="pixel-gold-text pixel-gold-text--md">UPLOAD YOUR PDF</h2>
          <p>Turn your own notes into a quiz, written by AI.</p>
        </div>

        <button type="button" className="pixel-back" onClick={onBack}>
          ◀ BACK
        </button>
      </div>

      {offline && (
        <p className="upload-warning">
          Offline Mode is on -- turn it off to generate questions. This needs the live server and a local AI model.
        </p>
      )}

      <form className="upload-form" onSubmit={handleSubmit}>
        <label className="upload-form__file">
          <input
            type="file"
            accept="application/pdf"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            disabled={loading}
          />
          {file ? file.name : "Choose a PDF…"}
        </label>

        <div className="upload-form__row">
          <span className="upload-form__label">Question type</span>
          <div className="upload-form__choices">
            {MODES.map((m) => (
              <button
                type="button"
                key={m.id}
                className={mode === m.id ? "upload-chip upload-chip--active" : "upload-chip"}
                onClick={() => setMode(m.id)}
                disabled={loading}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>

        <div className="upload-form__row">
          <span className="upload-form__label">How many questions</span>
          <div className="upload-form__choices">
            {COUNT_OPTIONS.map((n) => (
              <button
                type="button"
                key={n}
                className={count === n ? "upload-chip upload-chip--active" : "upload-chip"}
                onClick={() => setCount(n)}
                disabled={loading}
              >
                {n}
              </button>
            ))}
          </div>
        </div>

        {error && <p className="upload-warning">{error}</p>}

        <button type="submit" className="pixel-start" disabled={!file || loading || offline}>
          {loading ? "Generating…" : "Generate Questions"}
          <span>▶</span>
        </button>

        {loading && (
          <p className="upload-hint">This can take a minute or two on a local model -- hang tight.</p>
        )}
      </form>
    </section>
  );
}
