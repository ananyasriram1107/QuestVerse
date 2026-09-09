// JS port of ai/data/languages.csv + ai/dataset.py -- kept in sync by hand
// since there are only 5 rows. Powers the Programming Languages course
// while offline.
export const NUMERIC_FIELDS = new Set(["difficulty", "popularity", "year_created"]);
export const LIST_FIELDS = new Set(["use_cases"]);
export const CATEGORICAL_FIELDS = new Set(["paradigm", "typing"]);

export const LANGUAGES = [
  { language: "Python", difficulty: 1, popularity: 57.9, use_cases: ["AI", "Data Science", "Web Development"], year_created: 1991, paradigm: "Multi-paradigm", typing: "Dynamic" },
  { language: "JavaScript", difficulty: 2, popularity: 62.3, use_cases: ["Web Development", "Front-end", "Back-end"], year_created: 1995, paradigm: "Multi-paradigm", typing: "Dynamic" },
  { language: "Java", difficulty: 3, popularity: 30, use_cases: ["Enterprise", "Android", "Backend"], year_created: 1995, paradigm: "Object-oriented", typing: "Static" },
  { language: "C++", difficulty: 5, popularity: 23.5, use_cases: ["Game Development", "Systems", "Embedded"], year_created: 1985, paradigm: "Multi-paradigm", typing: "Static" },
  { language: "C#", difficulty: 3, popularity: 27, use_cases: ["Game Development", "Desktop", "Web"], year_created: 2000, paradigm: "Object-oriented", typing: "Static" },
];

const LANGUAGES_BY_NAME = new Map(LANGUAGES.map((row) => [row.language.toLowerCase(), row]));

export function getLanguage(name) {
  return LANGUAGES_BY_NAME.get(name.trim().toLowerCase()) ?? null;
}

export function tierForDifficulty(difficulty) {
  if (difficulty <= 2) return 1;
  if (difficulty === 3) return 2;
  return 3;
}
