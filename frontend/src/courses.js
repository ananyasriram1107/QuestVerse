// Shared course catalog -- must stay in sync with the courseIds the backend
// actually serves content for (see backend/course_content.py + ai/question_bank.py).
export const COURSES = [
  {
    id: "os",
    title: "Operating Systems",
    short: "OS",
    description: "Processes, memory, scheduling & concurrency",
    icon: "⚙",
  },
  {
    id: "dbms",
    title: "Database Systems",
    short: "DB",
    description: "SQL, transactions, indexing & normalization",
    icon: "▣",
  },
  {
    id: "dsa",
    title: "Data Structures & Algorithms",
    short: "DS",
    description: "Trees, graphs, algorithms & complexity",
    icon: "⌘",
  },
  {
    id: "lang",
    title: "Programming Languages",
    short: "LANG",
    description: "Paradigms, typing systems & language trivia",
    icon: "</>",
  },
  {
    id: "custom",
    title: "Upload Your Own",
    short: "PDF",
    description: "Turn your own notes or a chapter into an AI-written quiz",
    icon: "📄",
  },
];
