// JS port of backend/keyword_grader.py (OS/DBMS/DSA) and ai/short_ans.py
// (Programming Languages) -- deterministic only, no LLM, since this all
// has to work with zero network access.
import { getLanguage, NUMERIC_FIELDS, LIST_FIELDS, CATEGORICAL_FIELDS } from "./languageData";

function joinNaturally(items) {
  const list = [...items];
  if (list.length === 0) return "";
  if (list.length === 1) return list[0];
  if (list.length === 2) return `${list[0]} and ${list[1]}`;
  return `${list.slice(0, -1).join(", ")}, and ${list[list.length - 1]}`;
}

// ---- OS/DBMS/DSA keyword-cluster grading (mirrors keyword_grader.py) ----

function fallbackKeywordFeedback(userAnswer, matched, missing, correct, modelAnswer) {
  if (!userAnswer || !userAnswer.trim()) {
    return `You didn't write anything for this one -- here's the idea in a nutshell: ${modelAnswer}`;
  }
  if (correct && missing.length === 0) {
    return `Nice work -- your answer covers everything it needs to, including ${joinNaturally(matched)}.`;
  }
  if (correct) {
    return `Good answer overall. You clearly explained ${joinNaturally(matched)}, which is really the heart of it.`;
  }
  if (matched.length > 0) {
    return `You're on the right track -- you touched on ${joinNaturally(matched)}, but the answer is still missing a piece. Here's the fuller picture: ${modelAnswer}`;
  }
  return `That doesn't quite capture it yet. Here's what this one is really about: ${modelAnswer}`;
}

function gradeKeywordAnswer(question, userAnswer) {
  const clusters = question.keyword_clusters || [];
  const modelAnswer = question.model_answer || "";
  const normalized = (userAnswer || "").toLowerCase();

  const matched = [];
  const missing = [];
  for (const cluster of clusters) {
    const aliases = cluster.aliases || [];
    if (aliases.some((alias) => normalized.includes(alias.toLowerCase()))) {
      matched.push(cluster.name);
    } else {
      missing.push(cluster.name);
    }
  }

  const threshold = question.min_clusters_required ?? 2;
  const total = clusters.length || 1;
  const accuracy = Math.round((100 * matched.length) / total);
  const correct = matched.length >= threshold;
  const feedback = fallbackKeywordFeedback(userAnswer, matched, missing, correct, modelAnswer);

  return {
    accuracy,
    correct,
    matched_concepts: matched,
    missing_concepts: missing,
    correct_value: modelAnswer,
    feedback,
    graded_by: "deterministic",
  };
}

// ---- Programming Languages dataset grading (mirrors ai/short_ans.py) ----

const FIELD_DESCRIPTIONS = {
  year_created: "release year",
  popularity: "popularity in this dataset",
  difficulty: "difficulty rating on a 1-5 scale",
  paradigm: "programming paradigm",
  typing: "typing style",
  use_cases: "typical use cases",
};

const CONCEPT_EXPLANATIONS = {
  static: "static typing means the type of every variable is checked before the program ever runs, which catches type mistakes early but requires declaring types upfront",
  dynamic: "dynamic typing means types are checked while the program is running, which makes the language more flexible to write in but lets some type mistakes slip through until that line actually executes",
  "object-oriented": "object-oriented means code is organized around objects that bundle related data and behavior together",
  "multi-paradigm": "multi-paradigm means the language doesn't lock you into one style -- you can freely mix object-oriented, functional, and procedural code depending on what fits the problem",
  functional: "functional means the language favors building programs out of pure functions and avoiding changing state, rather than step-by-step instructions",
  procedural: "procedural means the program runs as a straightforward sequence of instructions and function calls, executed roughly top to bottom",
};

function explainConcept(value) {
  return CONCEPT_EXPLANATIONS[value.trim().toLowerCase()] || "";
}

const NUMERIC_TOLERANCE = { year_created: 2, popularity: 5, difficulty: 1 };

function numericScore(userAnswer, correctValue, field, language) {
  const description = FIELD_DESCRIPTIONS[field];
  const match = userAnswer.match(/-?\d+(\.\d+)?/);
  if (!match) {
    return [0, `That answer doesn't seem to include a number, so there's nothing to check it against -- for the record, ${description} for ${language} is ${correctValue}.`];
  }

  const guess = parseFloat(match[0]);
  const tolerance = NUMERIC_TOLERANCE[field] ?? 1;
  const diff = Math.abs(guess - correctValue);

  if (diff <= tolerance) {
    return [100, `That's right -- ${description} for ${language} really is ${correctValue}.`];
  }
  if (diff >= tolerance * 3) {
    return [0, `Not quite -- ${description} for ${language} is actually ${correctValue}, which is well off from your answer of ${guess}.`];
  }

  const score = Math.round(100 * (1 - (diff - tolerance) / (tolerance * 2)));
  return [Math.max(0, Math.min(100, score)), `Close, but not exact -- ${description} for ${language} is ${correctValue}, so your guess of ${guess} was off by ${diff}.`];
}

function categoricalScore(userAnswer, correctValue, field, language) {
  const description = FIELD_DESCRIPTIONS[field];
  const explanation = explainConcept(correctValue);
  const explanationClause = explanation ? ` -- ${explanation}` : "";

  const normalizedUser = userAnswer.trim().toLowerCase();
  const normalizedCorrect = correctValue.trim().toLowerCase();
  if (normalizedUser.includes(normalizedCorrect)) {
    return [100, `Exactly right -- ${language} is ${correctValue.toLowerCase()}${explanationClause}.`];
  }

  const synonyms = {
    dynamic: ["dynamically typed", "dynamic typing", "duck typed"],
    static: ["statically typed", "static typing"],
    "object-oriented": ["oop", "object oriented", "objectoriented"],
    "multi-paradigm": ["multiparadigm", "multi paradigm", "hybrid"],
  };
  for (const [canonical, aliases] of Object.entries(synonyms)) {
    if (canonical === normalizedCorrect && aliases.some((alias) => normalizedUser.includes(alias))) {
      return [100, `That's correct, just worded differently -- ${language} is ${correctValue.toLowerCase()}${explanationClause}.`];
    }
  }

  return [0, `Not quite -- ${description} for ${language} is actually ${correctValue}${explanationClause}.`];
}

function listScore(userAnswer, correctValues, language) {
  const normalizedUser = userAnswer.trim().toLowerCase();
  const hits = correctValues.filter((v) => normalizedUser.includes(v.toLowerCase()));
  const others = correctValues.filter((v) => !hits.includes(v));

  if (hits.length === 0) {
    return [0, `That doesn't match any of the typical use cases for ${language} in this dataset, which are ${joinNaturally(correctValues)}.`];
  }

  const score = Math.round((100 * hits.length) / correctValues.length);
  let sentence = `Good -- ${joinNaturally(hits)} ${hits.length === 1 ? "is" : "are"} right for ${language}.`;
  if (others.length > 0) {
    sentence += ` It's also commonly used for ${joinNaturally(others)}.`;
  }
  return [score, sentence];
}

function deterministicLanguageGrade(question, userAnswer) {
  const row = getLanguage(question.language);
  const field = question.field;
  const correctValue = row[field];
  const language = row.language;

  if (NUMERIC_FIELDS.has(field)) {
    const [score, note] = numericScore(userAnswer, correctValue, field, language);
    return { accuracy: score, correctValue, note };
  }
  if (LIST_FIELDS.has(field)) {
    const [score, note] = listScore(userAnswer, correctValue, language);
    return { accuracy: score, correctValue, note };
  }
  if (CATEGORICAL_FIELDS.has(field)) {
    const [score, note] = categoricalScore(userAnswer, correctValue, field, language);
    return { accuracy: score, correctValue, note };
  }
  return { accuracy: 0, correctValue, note: "Unknown field type." };
}

function gradeLanguageAnswer(question, userAnswer) {
  const PASS_THRESHOLD = 65;

  if (!userAnswer || !userAnswer.trim()) {
    const row = getLanguage(question.language);
    const field = question.field;
    const correctValue = row[field];
    const language = row.language;

    let verb = "is";
    let fact;
    if (LIST_FIELDS.has(field)) {
      verb = "are";
      fact = joinNaturally(correctValue);
    } else if (CATEGORICAL_FIELDS.has(field)) {
      const explanation = explainConcept(correctValue);
      fact = `${correctValue}${explanation ? ` -- ${explanation}` : ""}`;
    } else {
      fact = `${correctValue}`;
    }

    return {
      accuracy: 0,
      correct: false,
      correct_value: correctValue,
      feedback: `You didn't write anything for this one -- ${language}'s ${FIELD_DESCRIPTIONS[field]} ${verb} ${fact}.`,
      graded_by: "deterministic",
    };
  }

  const det = deterministicLanguageGrade(question, userAnswer);
  return {
    accuracy: det.accuracy,
    correct: det.accuracy >= PASS_THRESHOLD,
    correct_value: det.correctValue,
    feedback: det.note,
    graded_by: "deterministic",
  };
}

// ---- Entry point: mirrors backend/main.py's grade() ----

export function gradeOffline(question, answer) {
  const rawAnswer = answer || "";

  if (question.mode === "mcq") {
    const isCorrect = String(rawAnswer).trim().toLowerCase() === String(question.correct_answer).trim().toLowerCase();
    return [isCorrect, {
      correct_answer: question.correct_answer,
      your_answer: answer,
      explanation: question.explanation || "",
    }];
  }

  const result = question.courseId === "lang"
    ? gradeLanguageAnswer(question, rawAnswer)
    : gradeKeywordAnswer(question, rawAnswer);

  result.your_answer = answer;
  return [result.correct, result];
}
