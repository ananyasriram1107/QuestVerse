import { getFirstQuestionOffline, submitAnswerOffline, hasOfflineQuestion } from "./offline/offlineEngine";
import { isOfflineMode } from "./utils/offlineMode";

// Where the backend lives. Local dev falls back to the local server; a production build must be
// given VITE_API_BASE_URL (the Vercel project setting) -- it is a public URL, never a secret.
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || (import.meta.env.DEV ? "http://127.0.0.1:8010" : "")).replace(/\/+$/, "");
const NOT_CONFIGURED =
  "This copy of QuestVerse doesn't know where its server is (VITE_API_BASE_URL isn't set). Free Play still works offline.";

class ClientRejectedError extends Error {}

// ---- Accounts: every request carries the login token; hero ids become `u<user>.<hero>` ----
const TOKEN_KEY = "questverse_token_v1";
let currentUserId = null;

export const getToken = () => {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
};

const setToken = (token) => {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // storage unavailable -- the session just won't survive a refresh
  }
};

export function setCurrentUser(userId) {
  currentUserId = userId;
}

// The server keeps each hero's progress under the user's own id; the UI keeps using plain hero ids.
const serverStudent = (id) => (currentUserId && id && !/^u\d+\./.test(id) ? `u${currentUserId}.${id}` : id);

function apiFetch(url, options = {}) {
  const token = getToken();
  const headers = token ? { ...options.headers, Authorization: `Bearer ${token}` } : options.headers;
  return fetch(url, { ...options, headers }).then((response) => {
    if (response.status === 401 && token) {
      setToken(null);
      window.dispatchEvent(new Event("questverse:logout"));   // the session ended -- App returns to the login page
    }
    return response;
  });
}

async function fetchWithRetry(url, options = {}) {
  try {
    const response = await apiFetch(url, options);
    if (response.status >= 400 && response.status < 500) {
      // Deliberate server refusal (locked question, wrong student...): don't
      // retry, and show the server's own explanation.
      let detail = `Request failed (${response.status})`;
      try {
        detail = (await response.json()).detail || detail;
      } catch {
        // not JSON -- keep the generic message
      }
      throw new ClientRejectedError(detail);
    }
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    return response;
  } catch (firstError) {
    if (firstError instanceof ClientRejectedError) throw firstError;
    await new Promise((resolve) => setTimeout(resolve, 700));
    const retryResponse = await apiFetch(url, options);
    if (!retryResponse.ok) {
      throw new Error("Connection issue. Make sure the backend server is running.", { cause: firstError });
    }
    return retryResponse;
  }
}

// Real backend (see backend/main.py) is the primary source. When Offline
// Mode is switched on, or when the backend simply can't be reached, we
// serve the exact same response shapes from the in-browser offline engine
// (src/offline/) instead -- same four courses, same adaptive tier/XP math,
// same grading, just no network involved.
export async function getFirstQuestion(courseId = "os", mode = "mcq", startXp = 0, studentId = "") {
  if (isOfflineMode()) {
    return getFirstQuestionOffline(courseId, mode, startXp);
  }

  try {
    const response = await fetchWithRetry(
      `${API_BASE_URL}/question/first?courseId=${courseId}&mode=${mode}&start_xp=${startXp}&student_id=${encodeURIComponent(serverStudent(studentId))}`
    );
    return await response.json();
  } catch {
    return getFirstQuestionOffline(courseId, mode, startXp);
  }
}

// Resumes a server session after a page refresh; null if it expired/unknown.
export async function getSession(sessionId, studentId) {
  try {
    const response = await apiFetch(
      `${API_BASE_URL}/session/${encodeURIComponent(sessionId)}?student_id=${encodeURIComponent(serverStudent(studentId))}`
    );
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

// Quest report computed by the backend from the persisted attempt log.
export async function getDashboard(sessionId, studentId) {
  const response = await apiFetch(
    `${API_BASE_URL}/dashboard/${encodeURIComponent(sessionId)}?student_id=${encodeURIComponent(serverStudent(studentId))}`
  );
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      detail = (await response.json()).detail || detail;
    } catch {
      // not JSON -- keep the generic message
    }
    throw new Error(detail);
  }
  return response.json();
}

// Verbal hint from the backend's local Ollama model. Read-only on the server
// (no XP/attempt changes). No offline fallback and no auto-retry: the model can
// take a while, so the player retries explicitly from the hint bubble.
export async function requestAiHint(payload) {
  if (isOfflineMode() || !payload.session_id) {
    throw new Error("Hints need the live server. Switch Offline Mode off to ask your companion.");
  }
  let response;
  try {
    response = await apiFetch(`${API_BASE_URL}/hint/ai`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...payload, student_id: serverStudent(payload.student_id) }),
    });
  } catch {
    throw new Error("Can't reach the QuestVerse server. Make sure the backend is running.");
  }
  if (!response.ok) {
    let detail = `Your companion couldn't help right now (${response.status}).`;
    try {
      detail = (await response.json()).detail || detail;
    } catch {
      // not JSON -- keep the generic message
    }
    throw new Error(detail);
  }
  const data = await response.json();
  if (typeof data?.hint !== "string" || !data.hint) throw new Error("Your companion came back empty-handed. Try again.");
  return data.hint;
}

// ---- Levels: the backend owns progression; these just ask it. They have no
// offline fallback on purpose -- unlock state and XP can only come from the server.
export class ApiError extends Error {
  constructor(message, status, options) {
    super(message, options);
    this.status = status;
  }
}

// `looksRight(data)` guards against talking to the WRONG server: another program
// can answer on the same port (e.g. a different API whose /progress/{name} route
// happily matches /progress/me). Without this check its unexpected JSON would crash
// the map instead of explaining the problem.
async function levelRequest(path, options, looksRight = () => true) {
  if (!API_BASE_URL) throw new ApiError(NOT_CONFIGURED, 0);
  if (isOfflineMode()) {
    throw new ApiError("Levels need the live server. Switch Offline Mode off, or use Free Play.", 0);
  }
  let response;
  try {
    response = await apiFetch(`${API_BASE_URL}${path}`, options);
  } catch (cause) {
    throw new ApiError("Can't reach the QuestVerse server. Make sure the backend is running.", 0, { cause });
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      detail = (await response.json()).detail || detail;
    } catch {
      // not JSON -- keep the generic message
    }
    throw new ApiError(detail, response.status);
  }
  const data = await response.json();
  if (!looksRight(data)) {
    throw new ApiError(
      `The server at ${API_BASE_URL} answered ${path.split("?")[0]}, but not like the QuestVerse backend. ` +
        "Another program may be using that port: start the QuestVerse backend on the port the app expects " +
        "(see VITE_API_BASE_URL).",
      response.status
    );
  }
  return data;
}

const post = (body) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

const q = encodeURIComponent;

export const getProgress = (studentId) =>
  levelRequest(`/progress/me?student_id=${q(serverStudent(studentId))}`, undefined, (d) => Array.isArray(d?.stages) && d.stages.every((s) => Array.isArray(s?.levels)) && Boolean(d?.totals));

// resumeOnly: true when re-entering from a URL/refresh -- resume an unfinished
// run, never start a new one.
export const startLevel = (levelId, studentId, resumeOnly = false) =>
  levelRequest(`/levels/${q(levelId)}/start`, post({ student_id: serverStudent(studentId), resume_only: resumeOnly }),
    (d) => Boolean(d?.session_id && d?.question && d?.level_info));

export const completeLevel = (levelId, studentId, sessionId) =>
  levelRequest(`/levels/${q(levelId)}/complete`, post({ student_id: serverStudent(studentId), session_id: sessionId }),
    (d) => Boolean(d?.level && d?.xp));

export const getLevelResults = (levelId, studentId, sessionId) =>
  levelRequest(
    `/levels/${q(levelId)}/results?student_id=${q(serverStudent(studentId))}${sessionId ? `&session_id=${q(sessionId)}` : ""}`,
    undefined,
    (d) => Boolean(d?.level && d?.xp)
  );

export async function submitAnswer(payload) {
  if (isOfflineMode() || !payload.session_id) {
    return submitAnswerOffline(payload);
  }

  try {
    const response = await fetchWithRetry(`${API_BASE_URL}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...payload, student_id: serverStudent(payload.student_id) }),
    });
    return await response.json();
  } catch (err) {
    // A live backend session is authoritative: never silently re-grade it
    // offline (that would bypass server-side progression), just surface it.
    if (payload.session_id || !hasOfflineQuestion(payload.question_id)) {
      // The question came from the real backend's fuller content and has
      // no offline counterpart -- nothing to grade locally, so surface the
      // original connection error instead of silently breaking the quest.
      throw err;
    }
    return submitAnswerOffline(payload);
  }
}

// Generates a fresh "custom" course from an uploaded PDF via the real
// backend's local LLM (see backend/custom_upload.py), OCR-ing scanned pages
// automatically when the PDF has no selectable text. There's no offline
// equivalent for this one -- inventing original questions from arbitrary
// uploaded text isn't something the deterministic offline engine can do,
// so this always needs the live server and a running Ollama model.
export async function generateQuestionsFromPdf(file, mode, count) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("mode", mode);
  formData.append("count", String(count));

  const response = await apiFetch(`${API_BASE_URL}/custom/generate`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    let detail = "Couldn't generate questions from this PDF.";
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // response wasn't JSON -- fall back to the generic message
    }
    throw new Error(detail);
  }

  return response.json();
}


// ---- Account endpoints (these need the live server; there is no offline login) ----
async function accountRequest(path, options) {
  if (!API_BASE_URL) throw new ApiError(NOT_CONFIGURED, 0);
  let response;
  try {
    response = await apiFetch(`${API_BASE_URL}${path}`, options);
  } catch (cause) {
    throw new ApiError("Can't reach the QuestVerse server. Make sure the backend is running.", 0, { cause });
  }
  let body = null;
  try {
    body = await response.json();
  } catch {
    // not JSON
  }
  if (!response.ok) throw new ApiError(body?.detail || `Request failed (${response.status})`, response.status);
  return body;
}

export async function register(username, password, email) {
  const body = await accountRequest("/auth/register", post({ username, password, email: email || null }));
  setToken(body.token);
  return body.user;
}

export async function login(username, password) {
  const body = await accountRequest("/auth/login", post({ username, password }));
  setToken(body.token);
  return body.user;
}

// The signed-in user for the saved token, or null if there is none / it has expired.
export async function fetchMe() {
  if (!getToken()) return null;
  try {
    return (await accountRequest("/auth/me")).user;
  } catch (error) {
    if (error.status === 401) return null;
    throw error;
  }
}

export async function logout() {
  try {
    await accountRequest("/auth/logout", post({}));
  } catch {
    // already gone -- the local token is dropped either way
  }
  setToken(null);
}

export const getWeeklyReport = (week) => accountRequest(`/me/weekly-report${week ? `?week=${q(week)}` : ""}`);

export const updateEmail = (email) =>
  accountRequest("/me/email", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email }) });

export const getServerAchievements = () => accountRequest("/me/achievements");

export const putServerAchievements = (data) =>
  accountRequest("/me/achievements", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
