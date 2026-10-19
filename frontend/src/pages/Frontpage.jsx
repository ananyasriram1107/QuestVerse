import { useState } from "react";
import explorerSprite from "../assets/mascot-correct.png";
import questBg from "../assets/pixel-quest-result-bg.png";
import { COURSES } from "../courses";
import PdfUploadStage from "../components/PdfUploadStage";
import { MODES } from "../modes";

export default function FrontPage({ onLaunchSession, onOpenMap, onBackToMap, initialStage = "start" }) {
  const [stage, setStage] = useState(initialStage);
  const [selectedCourse, setSelectedCourse] = useState(null);

  const selectCourse = (course) => {
    setSelectedCourse(course);
    setStage("modes");
  };

  const selectMode = (mode) => {
    onLaunchSession?.({
      courseId: selectedCourse.id,
      courseTitle: selectedCourse.title,
      mode: mode.id,
    });
  };

  return (
    <div className="pixel-quest-page">
      <main className="pixel-content">

        <div className="pixel-logo pixel-logo--center">
          <div className="pixel-logo-box">Q</div>
          <span className="pixel-gold-text pixel-gold-text--sm">QUESTVERSE</span>
        </div>

        {/* START SCREEN */}
        {stage === "start" && (
          <section className="start-screen">

            <div className="pixel-small-title">
              ★ WELCOME ADVENTURER ★
            </div>

            <div className="title-brick-panel">
              <h1 className="pixel-gold-text">
                QUEST
                <br />
                VERSE
              </h1>

              <p>
                Your learning adventure begins here.
                <br />
                Choose your path, answer challenges, and level up your knowledge.
              </p>
            </div>

            <button
              className="pixel-start"
              onClick={() => (onOpenMap ? onOpenMap() : setStage("courses"))}
            >
              START QUEST
              <span>▶</span>
            </button>

            <img
              src={explorerSprite}
              alt="Explorer"
              className="pixel-hero-explorer"
            />

          </section>
        )}

        {/* COURSE SCREEN */}
        {stage === "courses" && (
          <section className="selection-screen">

            <div className="selection-heading">
              <div>
                <div className="pixel-small-title">
                  QUEST 01
                </div>

                <h2 className="pixel-gold-text pixel-gold-text--md">CHOOSE YOUR PATH</h2>

                <p>
                  Select a subject for your adventure.
                </p>
              </div>

              <button
                className="pixel-back"
                onClick={() => (onBackToMap ? onBackToMap() : setStage("start"))}
              >
                ◀ BACK
              </button>
            </div>

            <div className="course-grid">
              {COURSES.map((course, index) => (
                <button
                  className="pixel-card"
                  key={course.id}
                  onClick={() => selectCourse(course)}
                >
                  <div className="card-number">
                    LEVEL 0{index + 1}
                  </div>

                  <div className="card-icon">
                    {course.icon}
                  </div>

                  <div className="card-info">
                    <span>{course.short}</span>
                    <h3>{course.title}</h3>
                    <p>{course.description}</p>
                  </div>

                  <div className="card-action">
                    ENTER
                    <b>▶</b>
                  </div>
                </button>
              ))}

              <button
                className="pixel-card pixel-card--upload"
                onClick={() => setStage("upload")}
              >
                <div className="card-number">
                  YOUR OWN
                </div>

                <div className="card-icon">
                  ⬆
                </div>

                <div className="card-info">
                  <span>PDF</span>
                  <h3>Upload Your Own</h3>
                  <p>Turn any PDF into a quest -- we'll generate the questions.</p>
                </div>

                <div className="card-action">
                  UPLOAD
                  <b>▶</b>
                </div>
              </button>
            </div>

          </section>
        )}

        {/* MODE SCREEN */}
        {stage === "modes" && (
          <section className="selection-screen">

            <div className="selection-heading">
              <div>
                <div className="pixel-small-title">
                  QUEST 02
                </div>

                <h2 className="pixel-gold-text pixel-gold-text--md">CHOOSE YOUR CHALLENGE</h2>

                <p>
                  <strong>{selectedCourse?.short}</strong>{" "}
                  {selectedCourse?.title}
                </p>
              </div>

              <button
                className="pixel-back"
                onClick={() => setStage("courses")}
              >
                ◀ CHANGE
              </button>
            </div>

            <div className="mode-grid">
              {MODES.map((mode) => (
                <button
                  className="pixel-mode-card"
                  key={mode.id}
                  onClick={() => selectMode(mode)}
                >
                  <div className="mode-icon">
                    {mode.icon}
                  </div>

                  <div className="mode-tag">
                    {mode.tag}
                  </div>

                  <h3>{mode.title}</h3>

                  <p>{mode.description}</p>

                  <div className="mode-action">
                    START CHALLENGE
                    <b>▶</b>
                  </div>
                </button>
              ))}
            </div>

          </section>
        )}

        {/* UPLOAD SCREEN */}
        {stage === "upload" && (
          <PdfUploadStage
            onBack={() => setStage("courses")}
            onLaunch={onLaunchSession}
          />
        )}

      </main>

      <footer className="pixel-footer">
        <span>QUESTVERSE</span>
        <span>★ YOUR ADVENTURE AWAITS ★</span>
      </footer>

      <style>{`

        * {
          box-sizing: border-box;
        }

        .pixel-quest-page {
          min-height: 100vh;
          width: 100%;
          position: relative;
          display: flex;
          flex-direction: column;

          background: url(${questBg}) center / cover no-repeat;
          image-rendering: pixelated;

          color: #2c1a0a;

          font-family:
            "Trebuchet MS",
            "Arial Black",
            sans-serif;
        }

        .pixel-gold-text {
          font-family: "Press Start 2P", "Arial Black", sans-serif;
          background: linear-gradient(180deg, #fff3b0 0%, #ffcf4d 45%, #f2921f 100%);
          -webkit-background-clip: text;
          background-clip: text;
          color: transparent;
          text-shadow:
            -3px -3px 0 #6b3a12, 3px -3px 0 #6b3a12, -3px 3px 0 #6b3a12, 3px 3px 0 #6b3a12,
            -3px 0 0 #6b3a12, 3px 0 0 #6b3a12, 0 -3px 0 #6b3a12, 0 3px 0 #6b3a12,
            0 6px 0 #8a4b1f, 0 10px 0 #4a270f;
        }

        .pixel-gold-text--sm {
          text-shadow:
            -1px -1px 0 #6b3a12, 1px -1px 0 #6b3a12, -1px 1px 0 #6b3a12, 1px 1px 0 #6b3a12,
            0 3px 0 #8a4b1f;
        }

        .pixel-gold-text--md {
          text-shadow:
            -2px -2px 0 #6b3a12, 2px -2px 0 #6b3a12, -2px 2px 0 #6b3a12, 2px 2px 0 #6b3a12,
            -2px 0 0 #6b3a12, 2px 0 0 #6b3a12, 0 -2px 0 #6b3a12, 0 2px 0 #6b3a12,
            0 5px 0 #8a4b1f;
        }

        /* LOGO */

        .pixel-logo {
          display: flex;
          align-items: center;
          gap: 14px;
        }

        .pixel-logo span {
          font-size: 14px;
          letter-spacing: 2px;
        }

        .pixel-logo--center {
          justify-content: center;
        }

        .pixel-logo-box {
          width: 42px;
          height: 42px;

          display: grid;
          place-items: center;

          background: linear-gradient(180deg, #ffe8a3 0%, #f0a92e 60%, #c9791a 100%);
          color: #5c2f12;

          border: 4px solid #3d2410;
          box-shadow: 4px 4px 0 #3d2410;

          font-family: "Press Start 2P", "Arial Black", sans-serif;
          font-size: 18px;
        }

        /* MAIN */

        .pixel-content {
          flex: 1;
          width: min(1150px, 88%);
          margin: auto;

          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 30px;

          padding: 40px 0;

          position: relative;
          z-index: 2;
        }

        /* START */

        .start-screen {
          width: 100%;
          max-width: 720px;

          display: flex;
          flex-direction: column;
          align-items: center;
          text-align: center;

          position: relative;
        }

        .pixel-small-title {
          color: #fff3c9;

          font-family: "Press Start 2P", "Arial Black", sans-serif;
          font-size: 11px;

          letter-spacing: 2px;

          margin-bottom: 22px;

          text-shadow: 2px 2px 0 #3d2410;
        }

        .title-brick-panel {
          margin: 0 0 34px;
          padding: 40px 56px;

          background-color: #f4c752;
          background-image:
            repeating-linear-gradient(90deg, #d89a2e 0 6px, transparent 6px 54px),
            repeating-linear-gradient(0deg, #d89a2e 0 6px, transparent 6px 54px);

          border: 6px solid #3d2410;
          box-shadow: 10px 10px 0 #3d2410;
        }

        .start-screen h1 {
          margin: 0 0 26px;

          font-family: "Press Start 2P", "Arial Black", sans-serif;

          font-size: clamp(34px, 8vw, 62px);

          line-height: 1.35;
          letter-spacing: 1px;
        }

        .start-screen p {
          margin: 0;

          max-width: 46ch;

          color: #4a2710;

          font-size: 16px;
          font-weight: 700;
          line-height: 1.7;
        }

        .pixel-start {
          min-width: 260px;

          padding: 18px 26px;

          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 16px;

          background: linear-gradient(180deg, #ffe8a3 0%, #f0a92e 55%, #c9791a 100%);
          color: #4a2710;

          border: 4px solid #3d2410;
          box-shadow: 6px 6px 0 #3d2410;

          font-family: "Press Start 2P", "Arial Black", sans-serif;
          font-size: 13px;

          cursor: pointer;

          transition: 0.15s;
        }

        .pixel-start:hover {
          transform: translate(3px, 3px);
          box-shadow: 3px 3px 0 #3d2410;
        }

        .pixel-start span {
          font-size: 16px;
        }

        .pixel-hero-explorer {
          position: relative;
          width: 96px;
          height: 96px;

          object-fit: contain;

          image-rendering: pixelated;

          margin-top: 34px;

          filter: drop-shadow(5px 6px 0 rgba(30, 20, 10, 0.4));

          animation: bounce 2s ease-in-out infinite;
        }

        @keyframes bounce {
          0%, 100% {
            transform: translateY(0);
          }

          50% {
            transform: translateY(-9px);
          }
        }

        /* SELECTION */

        .selection-screen {
          width: 100%;
        }

        .selection-heading {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;

          margin-bottom: 38px;
        }

        .selection-heading h2 {
          margin: 18px 0 0;

          font-family: "Press Start 2P", "Arial Black", sans-serif;
          font-size: clamp(20px, 3.6vw, 32px);

          line-height: 1.6;
        }

        .selection-heading p {
          margin: 22px 0 0;

          color: #fff6e2;

          font-size: 15px;
          font-weight: 700;

          text-shadow: 2px 2px 0 rgba(61, 36, 16, 0.85);
        }

        .selection-heading p strong {
          color: #ffe8a3;
        }

        .pixel-back {
          padding: 13px 18px;

          background: linear-gradient(180deg, #ffe8a3 0%, #f0a92e 100%);

          border: 4px solid #3d2410;
          box-shadow: 4px 4px 0 #3d2410;

          color: #4a2710;

          font-family: "Press Start 2P", "Arial Black", sans-serif;

          font-size: 10px;

          cursor: pointer;
        }

        .pixel-back:hover {
          transform: translate(2px, 2px);
          box-shadow: 2px 2px 0 #3d2410;
        }

        /* COURSE CARDS */

        .course-grid {
          display: grid;

          grid-template-columns: repeat(4, 1fr);

          gap: 18px;
        }

        .pixel-card,
        .pixel-mode-card {
          min-height: 340px;

          padding: 24px;

          display: flex;
          flex-direction: column;
          justify-content: space-between;

          text-align: left;

          background: linear-gradient(160deg, #fbe3a5 0%, #eec678 55%, #d9a94f 100%);

          border: 5px solid #3d2410;

          box-shadow: 7px 7px 0 #3d2410;

          color: #4a2710;

          font-family: inherit;

          cursor: pointer;

          transition: 0.15s;
        }

        .pixel-card:hover,
        .pixel-mode-card:hover {
          transform: translate(3px, 3px);

          box-shadow: 4px 4px 0 #3d2410;

          background: linear-gradient(160deg, #fff1cc 0%, #f3d38b 55%, #e2b662 100%);
        }

        .card-number {
          color: #7a5326;

          font-size: 10px;
          font-weight: 900;

          letter-spacing: 1px;
        }

        .card-icon {
          font-size: 54px;

          color: #a4501e;

          text-shadow: 3px 3px 0 rgba(61, 36, 16, 0.25);
        }

        .card-info span {
          color: #a4501e;

          font-size: 11px;
          font-weight: 900;

          letter-spacing: 2px;
        }

        .card-info h3 {
          margin: 8px 0;

          font-size: 22px;

          line-height: 1.1;
        }

        .card-info p {
          margin: 0;

          color: #5c3d1c;

          font-size: 13px;

          line-height: 1.5;
        }

        .card-action,
        .mode-action {
          padding-top: 18px;

          border-top: 3px dashed #a4501e;

          display: flex;
          justify-content: space-between;

          color: #5c3d1c;

          font-size: 10px;
          font-weight: 900;

          letter-spacing: 1px;
        }

        .card-action b,
        .mode-action b {
          color: #a4501e;
        }

        .pixel-card--upload {
          background: repeating-linear-gradient(
            135deg,
            #f4c752 0 14px,
            #ecb84a 14px 28px
          );
          border-style: dashed;
        }

        .pixel-card--upload:hover {
          background: repeating-linear-gradient(
            135deg,
            #fff1cc 0 14px,
            #f3d38b 14px 28px
          );
        }

        /* MODES */

        .mode-grid {
          display: grid;

          grid-template-columns: repeat(2, 1fr);

          gap: 22px;
        }

        .pixel-mode-card {
          min-height: 300px;

          padding: 30px;

          position: relative;
        }

        .mode-icon {
          width: 62px;
          height: 62px;

          display: grid;
          place-items: center;

          background: linear-gradient(180deg, #ffe8a3 0%, #c9791a 100%);

          border: 4px solid #3d2410;

          box-shadow: 4px 4px 0 #3d2410;

          color: #4a2710;

          font-size: 28px;
        }

        .mode-tag {
          position: absolute;

          right: 25px;
          top: 30px;

          padding: 7px 10px;

          background: #f0a92e;

          border: 3px solid #3d2410;

          font-size: 9px;

          font-weight: 900;

          color: #3d2410;
        }

        .pixel-mode-card h3 {
          margin: 42px 0 12px;

          font-size: 26px;
        }

        .pixel-mode-card p {
          margin: 0 0 30px;

          color: #5c3d1c;

          font-size: 14px;

          line-height: 1.6;
        }

        /* PDF UPLOAD */

        .upload-warning {
          margin: 0 0 20px;

          padding: 12px 16px;

          background: #ffd9c9;
          border: 3px solid #7a2a12;

          color: #7a2a12;

          font-size: 13px;
          font-weight: 700;
        }

        .upload-form {
          display: grid;
          gap: 20px;

          max-width: 520px;
        }

        .upload-form__file {
          display: flex;
          align-items: center;

          padding: 16px 20px;

          background: linear-gradient(160deg, #fbe3a5 0%, #eec678 55%, #d9a94f 100%);
          border: 4px solid #3d2410;
          box-shadow: 5px 5px 0 #3d2410;

          color: #4a2710;

          font-weight: 700;

          cursor: pointer;
        }

        .upload-form__file input {
          display: none;
        }

        .upload-form__row {
          display: grid;
          gap: 10px;
        }

        .upload-form__label {
          color: #fff6e2;

          font-size: 11px;
          font-weight: 900;
          letter-spacing: 1px;
          text-transform: uppercase;

          text-shadow: 2px 2px 0 rgba(61, 36, 16, 0.85);
        }

        .upload-form__choices {
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
        }

        .upload-chip {
          padding: 10px 18px;

          background: #fff1cc;
          border: 3px solid #3d2410;
          box-shadow: 3px 3px 0 #3d2410;

          color: #4a2710;
          font-weight: 800;

          cursor: pointer;

          transition: 0.15s;
        }

        .upload-chip--active {
          background: linear-gradient(180deg, #ffe8a3 0%, #f0a92e 100%);
        }

        .upload-chip:hover:not(:disabled) {
          transform: translate(2px, 2px);
          box-shadow: 1px 1px 0 #3d2410;
        }

        .upload-hint {
          margin: 0;

          color: #fff6e2;

          font-size: 12px;

          text-shadow: 2px 2px 0 rgba(61, 36, 16, 0.85);
        }

        /* FOOTER */

        .pixel-footer {
          height: 56px;

          padding: 0 6vw;

          display: flex;
          justify-content: space-between;
          align-items: center;

          background: rgba(43, 26, 10, 0.45);

          border-top: 4px solid #2c1a0a;

          position: relative;
          z-index: 5;

          color: #fff3c9;

          font-size: 9px;
          font-weight: 900;

          letter-spacing: 1px;
        }

        /* RESPONSIVE */

        @media (max-width: 1050px) {

          .course-grid {
            grid-template-columns: repeat(2, 1fr);
          }

        }

        @media (max-width: 900px) {

          .course-grid,
          .mode-grid {
            grid-template-columns: 1fr;
          }

        }

        @media (max-width: 550px) {

          .pixel-content {
            width: 90%;
          }

          .title-brick-panel {
            padding: 28px 26px;
          }

          .selection-heading {
            flex-direction: column;
            gap: 20px;
          }

          .pixel-footer {
            padding: 0 20px;
          }

        }

      `}</style>
    </div>
  );
}
