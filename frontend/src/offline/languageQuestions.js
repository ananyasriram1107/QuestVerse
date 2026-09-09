// JS port of ai/question_bank.py -- builds the Programming Languages course
// bank straight from languageData.js, same as the backend does from the CSV.
import { LANGUAGES, tierForDifficulty } from "./languageData";

export const FIELD_QUESTION_TEXT = {
  year_created: "What year was {language} created?",
  popularity: "Roughly what percentage popularity does {language} have in this dataset?",
  difficulty: "On a scale of 1 (easiest) to 5 (hardest), how difficult is {language} rated?",
  paradigm: "What programming paradigm does {language} use?",
  typing: "Is {language} statically or dynamically typed?",
  use_cases: "Name a typical use case for {language}.",
};

const MCQ_FIELDS = ["year_created", "difficulty", "paradigm", "typing"];

const MCQ_EXPLANATION_TEXT = {
  year_created: "{language} was first released in {value}.",
  difficulty: "In this dataset, {language} carries a difficulty rating of {value}/5.",
  paradigm: "{language} follows a {value} programming paradigm.",
  typing: "{language} uses {value} typing.",
};

function fmt(value) {
  if (typeof value === "number" && Number.isInteger(value)) {
    return String(value);
  }
  return String(value);
}

function fill(template, language) {
  return template.replace("{language}", language);
}

function mcqOptions(field, correctValue) {
  const pool = new Set(LANGUAGES.map((row) => row[field]));
  const distractors = [...pool].filter((v) => fmt(v) !== fmt(correctValue));
  distractors.sort(() => Math.random() - 0.5);
  const options = distractors.slice(0, 3).map(fmt).concat(fmt(correctValue));
  options.sort(() => Math.random() - 0.5);
  return options;
}

function buildMcqBank() {
  const questions = [];
  for (const row of LANGUAGES) {
    for (const field of MCQ_FIELDS) {
      const correctValue = row[field];
      const options = mcqOptions(field, correctValue);
      if (new Set(options).size < 2) {
        continue;
      }
      questions.push({
        id: `lang-mcq-${row.language.toLowerCase()}-${field}`,
        courseId: "lang",
        mode: "mcq",
        tier: tierForDifficulty(row.difficulty),
        prompt: fill(FIELD_QUESTION_TEXT[field], row.language),
        options,
        correct_answer: fmt(correctValue),
        explanation: MCQ_EXPLANATION_TEXT[field]
          .replace("{language}", row.language)
          .replace("{value}", fmt(correctValue)),
      });
    }
  }
  return questions;
}

export function makeShortAnswerQuestion(language, field) {
  const row = getLanguageRow(language);
  return {
    id: `lang-sa-${language.toLowerCase()}-${field}`,
    courseId: "lang",
    mode: "short_answer",
    language: row.language,
    field,
    prompt: fill(FIELD_QUESTION_TEXT[field], row.language),
    tier: tierForDifficulty(row.difficulty),
  };
}

function getLanguageRow(language) {
  const row = LANGUAGES.find((r) => r.language.toLowerCase() === language.toLowerCase());
  if (!row) {
    throw new Error(`Unknown language: ${language}`);
  }
  return row;
}

function buildShortAnswerBank() {
  const questions = [];
  for (const row of LANGUAGES) {
    for (const field of Object.keys(FIELD_QUESTION_TEXT)) {
      questions.push(makeShortAnswerQuestion(row.language, field));
    }
  }
  return questions;
}

export const LANG_MCQ_QUESTIONS = buildMcqBank();
export const LANG_SHORT_ANSWER_QUESTIONS = buildShortAnswerBank();
