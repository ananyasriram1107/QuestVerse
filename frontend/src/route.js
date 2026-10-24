import { useEffect, useState } from "react";

// Minimal hash router. The app had no router, and the quiz flow needs real
// URLs so that refresh, Back and Forward land on the right screen:
//
//   #/                         title screen
//   #/hero                     choose your hero (the student)
//   #/map                      stage / level map
//   #/play/<levelId>           a level's quiz
//   #/results/<levelId>/<sessionId>   results of a finished run
//   #/review/<levelId>/<sessionId>    review of a finished run (guessing pattern)
//   #/report                    weekly progress report
//   #/free  and  #/upload      free-play course picker / PDF upload (existing screens)
//
// Routes only say WHAT to show. Whether a level may be opened is decided by
// the backend, never by the URL.

export function parseHash(hash = window.location.hash) {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  const [name, a, b] = parts;
  switch (name) {
    case "hero":
      return { name: "hero" };
    case "map":
      return { name: "map" };
    case "play":
      return a ? { name: "play", levelId: a } : { name: "map" };
    case "results":
      return a ? { name: "results", levelId: a, sessionId: b ?? null } : { name: "map" };
    case "review":
      return a && b ? { name: "review", levelId: a, sessionId: b } : { name: "map" };
    case "report":
      return { name: "report" };
    case "free":
      return { name: "free" };
    case "upload":
      return { name: "upload" };
    default:
      return { name: "title" };
  }
}

export function pathFor(route) {
  switch (route.name) {
    case "hero":
      return "#/hero";
    case "map":
      return "#/map";
    case "play":
      return `#/play/${encodeURIComponent(route.levelId)}`;
    case "results":
      return `#/results/${encodeURIComponent(route.levelId)}${route.sessionId ? `/${encodeURIComponent(route.sessionId)}` : ""}`;
    case "review":
      return `#/review/${encodeURIComponent(route.levelId)}/${encodeURIComponent(route.sessionId)}`;
    case "report":
      return "#/report";
    case "free":
      return "#/free";
    case "upload":
      return "#/upload";
    default:
      return "#/";
  }
}

// `replace` swaps the current history entry (used when a quiz finishes, so Back
// from the results goes to the map instead of back into the finished quiz).
export function navigate(route, { replace = false } = {}) {
  const target = pathFor(route);
  if (replace) {
    window.history.replaceState(null, "", target);
  } else if (window.location.hash !== target) {
    window.history.pushState(null, "", target);
  }
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function useRoute() {
  const [route, setRoute] = useState(() => parseHash());
  useEffect(() => {
    const onChange = () => setRoute(parseHash());
    window.addEventListener("popstate", onChange);
    window.addEventListener("hashchange", onChange);
    return () => {
      window.removeEventListener("popstate", onChange);
      window.removeEventListener("hashchange", onChange);
    };
  }, []);
  return route;
}
