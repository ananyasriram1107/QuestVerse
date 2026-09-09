import { getFirstQuestionOffline, submitAnswerOffline, hasOfflineQuestion } from "./offline/offlineEngine";
import { isOfflineMode } from "./utils/offlineMode";

const API_BASE_URL = "http://127.0.0.1:8000";

async function fetchWithRetry(url, options = {}) {
  try {
    const response = await fetch(url, options);
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    return response;
  } catch (firstError) {
    await new Promise((resolve) => setTimeout(resolve, 700));
    const retryResponse = await fetch(url, options);
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
export async function getFirstQuestion(courseId = "os", mode = "mcq") {
  if (isOfflineMode()) {
    return getFirstQuestionOffline(courseId, mode);
  }

  try {
    const response = await fetchWithRetry(
      `${API_BASE_URL}/question/first?courseId=${courseId}&mode=${mode}`
    );
    return await response.json();
  } catch {
    return getFirstQuestionOffline(courseId, mode);
  }
}

export async function submitAnswer(payload) {
  if (isOfflineMode()) {
    return submitAnswerOffline(payload);
  }

  try {
    const response = await fetchWithRetry(`${API_BASE_URL}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return await response.json();
  } catch (err) {
    if (!hasOfflineQuestion(payload.question_id)) {
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

  const response = await fetch(`${API_BASE_URL}/custom/generate`, {
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
