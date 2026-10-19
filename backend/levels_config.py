"""
World -> Stage -> Level configuration.

This file is the only place the progression structure is defined. It holds no
questions: each level is a *selector* that is resolved against the real
question banks (course_content.py, ai/question_bank.py, ...) at runtime, so
adding a course, a stage or a level means editing this data, not any code.

Hierarchy
    World  : the whole adventure
    Stage  : a themed region; unlocks when every level of the previous stage is done
    Level  : one fixed question set (a quiz) for one course; unlocks when the
             previous level in its stage is done
    Quiz   : the level's questions, answered through the existing /answer flow

The four stages below are an initial design, in difficulty order. To change the
adventure, edit STAGES / COURSE_ORDER / the selectors -- nothing else.

Completion requirement (all levels): every question in the set must be answered
correctly. Wrong answers can be retried (existing behaviour), so this matches the
existing correct-answer gating.

Rewards: the existing XP rule (tier x 10 per correct answer, adaptive tier) is
unchanged. What is new is that each question's XP is granted at most once per
student per level (see attempt_store.xp_awards), so replays and abandoned runs
cannot farm it.
"""

WORLD = {
    "id": "questverse",
    "name": "QuestVerse",
    "description": "A world of quests that grow with what you know.",
}

# Order of courses inside every stage.
COURSE_ORDER = ["os", "dbms", "dsa", "lang"]

COURSE_TITLES = {
    "os": "Operating Systems",
    "dbms": "Database Systems",
    "dsa": "Data Structures & Algorithms",
    "lang": "Programming Languages",
    "custom": "Upload Your Own",
}

# The least a level may contain. Enforced when the catalog is built, when a level is
# started (main.start_level) and by the guesswork analysis (guess_analysis.CONFIG).
MIN_LEVEL_QUESTIONS = 5


def _pool(mode: str, tier: int, count: int) -> dict:
    return {"mode": mode, "tier": tier, "count": count}


# Each stage describes the question selector shared by its levels:
#   pools          : ordered (mode, tier, count) slices of a course's bank. A level takes the
#                    first `count` questions (stable id order) of each pool, in order, until
#                    it has max_questions. A single (mode, tier) pool only holds 2 questions
#                    for most courses, which is why levels used to have 2-4 questions.
#   max_questions  : cap on the set size
#   label          : appended to the course title to name the level
# Questions inside a level are served easiest tier first. Difficulty rises from stage to
# stage by moving to harder tiers and, in "The Trial Grounds", to answers in your own words.
STAGES = [
    {
        "id": "grove",
        "name": "The Beginner's Grove",
        "description": "Sun-dappled clearings where every adventurer takes their first steps.",
        "theme": "forest",
        "label": "Foundations",
        "difficulty": "Easy",
        "selector": {"pools": [_pool("mcq", 1, 2), _pool("short_answer", 1, 2), _pool("mcq", 2, 1)],
                     "max_questions": 5},
    },
    {
        "id": "caverns",
        "name": "The Knowledge Caverns",
        "description": "Echoing tunnels where the questions run deeper than they look.",
        "theme": "teal",
        "label": "Depths",
        "difficulty": "Medium",
        "selector": {"pools": [_pool("mcq", 2, 2), _pool("short_answer", 1, 1), _pool("short_answer", 2, 2)],
                     "max_questions": 5},
    },
    {
        "id": "trials",
        "name": "The Trial Grounds",
        "description": "Prove it in your own words: no options to lean on here.",
        "theme": "steel",
        "label": "Trial",
        "difficulty": "Hard",
        "selector": {"pools": [_pool("short_answer", 1, 1), _pool("short_answer", 2, 2), _pool("short_answer", 3, 2)],
                     "max_questions": 5},
    },
    {
        "id": "boss",
        "name": "The Boss Realm",
        "description": "The hardest questions in the land, guarding the treasure.",
        "theme": "violet",
        "label": "Boss Challenge",
        "difficulty": "Boss",
        "selector": {"pools": [_pool("short_answer", 2, 1), _pool("mcq", 3, 2), _pool("short_answer", 3, 2)],
                     "max_questions": 5},
    },
]

# Placeholder for the rule text shown in the UI.
COMPLETION_REQUIREMENT = "Answer every question correctly (wrong answers can be retried)."
REWARD_DESCRIPTION = "Tier x 10 XP per correct answer, earned once per question."

# Stars shown on a result, from first-try accuracy (purely presentational).
STAR_THRESHOLDS = {3: 80.0, 2: 50.0}


def build_levels() -> list:
    """Flat, ordered list of level definitions (without resolved questions)."""
    levels = []
    for stage_index, stage in enumerate(STAGES):
        for course_index, course_id in enumerate(COURSE_ORDER):
            levels.append({
                "id": f"{stage['id']}-{course_id}",
                "stage_id": stage["id"],
                "order": course_index,
                "global_order": len(levels),
                "course_id": course_id,
                "name": f"{COURSE_TITLES[course_id]}: {stage['label']}",
                "selector": stage["selector"],
            })
    return levels
