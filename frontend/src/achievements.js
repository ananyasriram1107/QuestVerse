// Achievement/quest definitions for the Achievements page. Each one tracks
// a lifetime stat (see utils/achievementStore.js) against a target -- e.g.
// "Complete 3 MCQs" reads stats.totalMcqAnswered and unlocks once it's >= 3.
export const ACHIEVEMENTS = [
  {
    id: "mcq_3",
    icon: "🥉",
    label: "Quiz Rookie",
    description: "Complete 3 multiple choice questions.",
    statKey: "totalMcqAnswered",
    target: 3,
  },
  {
    id: "mcq_15",
    icon: "🥈",
    label: "Quiz Veteran",
    description: "Complete 15 multiple choice questions.",
    statKey: "totalMcqAnswered",
    target: 15,
  },
  {
    id: "short_5",
    icon: "✍️",
    label: "Wordsmith",
    description: "Complete 5 short-answer questions.",
    statKey: "totalShortAnswered",
    target: 5,
  },
  {
    id: "correct_10",
    icon: "🎯",
    label: "Sharp Shooter",
    description: "Answer 10 questions correctly.",
    statKey: "totalCorrect",
    target: 10,
  },
  {
    id: "streak_5",
    icon: "🔥",
    label: "On Fire",
    description: "Reach a 5-question correct streak.",
    statKey: "longestStreakEver",
    target: 5,
  },
];
