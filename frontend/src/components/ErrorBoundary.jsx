import { Component } from "react";

// Without a boundary, one render error unmounts the whole app and leaves a blank
// page. This shows the real error message instead (it is also logged to the
// console) and lets the player go back.
export default class ErrorBoundary extends Component {
  state = { error: null };

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("QuestVerse screen crashed:", error, info?.componentStack);
  }

  render() {
    if (!this.state.error) {
      return this.props.children;
    }
    return (
      <main className="loading-screen" role="alert">
        <div className="stage-map__status stage-map__status--error">
          <strong>Something went wrong on this screen</strong>
          <p>{String(this.state.error?.message || this.state.error)}</p>
          <div className="stage-map__actions">
            <button type="button" className="stage-map__continue" onClick={() => window.location.reload()}>
              RELOAD
            </button>
            <button
              type="button"
              className="stage-map__secondary"
              onClick={() => {
                window.location.hash = "#/";
                window.location.reload();
              }}
            >
              TITLE SCREEN
            </button>
          </div>
        </div>
      </main>
    );
  }
}
