// The quest formats the backend actually serves for every course (see
// backend/main.py -- mode "mcq" or "short_answer"). Shared by the course
// picker and the stage map so both list exactly the same formats.
export const MODES = [
  {
    id: "mcq",
    title: "Multiple Choice",
    description: "Choose the correct answer from four options.",
    icon: "✓",
    tag: "QUICK",
  },
  {
    id: "short_answer",
    title: "Short Answer",
    description: "Explain the concept in your own words.",
    icon: "✎",
    tag: "CONCEPT",
  },
];
