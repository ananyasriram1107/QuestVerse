// Which hero (student) is playing on this device. The app has no login, so the
// chosen character's id is the student id the backend keeps progress under.
// This remembers only WHO is playing -- all progress lives on the backend.
const STUDENT_KEY = "questverse_student_v1";

export function loadStudentId() {
  try {
    return localStorage.getItem(STUDENT_KEY) || null;
  } catch {
    return null;
  }
}

export function saveStudentId(studentId) {
  try {
    if (studentId) localStorage.setItem(STUDENT_KEY, studentId);
    else localStorage.removeItem(STUDENT_KEY);
  } catch {
    // storage unavailable -- the hero just has to be picked again next visit
  }
}
