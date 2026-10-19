"""
Progression rules: which stages/levels exist, and which are open for a student.

Pure functions only -- no HTTP, no database -- so the rules are easy to read
and test. The database supplies two facts per student (which levels they have
completed, which they have an unfinished session for) and everything else is
derived here.

Rules
  1. A level's question set is fixed: the questions of its course that match the
     stage selector, in a stable order, capped at max_questions. Empty sets are
     dropped, so a level/stage only appears once the banks have content for it.
  2. The first level of the first stage is open to a new student.
  3. Within a stage, a level opens when the previous level of that stage has been
     completed at least once.
  4. A stage opens when EVERY level of the previous stage has been completed.
  5. A completed level stays completed forever (replayable, but it earns no new XP
     for questions whose XP was already granted -- see attempt_store.xp_awards).
  6. A level is "in_progress" only if the student has an unfinished session for
     it; merely being open or having been viewed changes nothing.
"""

from typing import Optional

from levels_config import (
    COMPLETION_REQUIREMENT, COURSE_TITLES, REWARD_DESCRIPTION, STAGES, STAR_THRESHOLDS, WORLD, build_levels,
)

TIER_WORDS = {1: "easy", 2: "medium", 3: "hard"}
MODE_WORDS = {"mcq": "multiple-choice", "short_answer": "short-answer"}


def resolve_question_ids(level: dict, all_questions: list) -> list:
    """The level's fixed question set, as ids, in a stable order."""
    sel = level["selector"]
    pool = [q for q in all_questions
            if q["courseId"] == level["course_id"] and q["mode"] in sel["modes"] and q["tier"] in sel["tiers"]]
    pool.sort(key=lambda q: (q["tier"], sel["modes"].index(q["mode"]), str(q["id"])))
    return [str(q["id"]) for q in pool[: sel["max_questions"]]]


def _describe(level: dict, questions: list) -> str:
    modes = sorted({q["mode"] for q in questions}, key=lambda m: level["selector"]["modes"].index(m))
    tiers = sorted({q["tier"] for q in questions})
    fmt = " and ".join(MODE_WORDS.get(m, m) for m in modes)
    diff = " to ".join(dict.fromkeys(TIER_WORDS[t] for t in (tiers[0], tiers[-1])))
    return f"{len(questions)} {fmt} questions on {COURSE_TITLES.get(level['course_id'], level['course_id'])} ({diff})."


def build_catalog(all_questions: list) -> dict:
    """Stages and levels with their resolved question sets."""
    by_id = {str(q["id"]): q for q in all_questions}
    levels_by_stage: dict = {}
    for level in build_levels():
        ids = resolve_question_ids(level, all_questions)
        if not ids:
            continue
        questions = [by_id[i] for i in ids]
        entry = {
            "id": level["id"],
            "stage_id": level["stage_id"],
            "order": len(levels_by_stage.setdefault(level["stage_id"], [])),
            "course_id": level["course_id"],
            "name": level["name"],
            "description": _describe(level, questions),
            "question_ids": ids,
            "question_count": len(ids),
            "formats": sorted({q["mode"] for q in questions}),
            "start_tier": min(q["tier"] for q in questions),
            "completion_requirement": COMPLETION_REQUIREMENT,
            "reward": REWARD_DESCRIPTION,
        }
        levels_by_stage[level["stage_id"]].append(entry)

    stages = []
    for stage in STAGES:
        levels = levels_by_stage.get(stage["id"])
        if not levels:
            continue
        stages.append({k: stage[k] for k in ("id", "name", "description", "theme", "difficulty")} | {"levels": levels})
    flat = [lv for st in stages for lv in st["levels"]]
    for i, lv in enumerate(flat):
        lv["global_order"] = i
    return {"world": WORLD, "stages": stages, "levels": {lv["id"]: lv for lv in flat}, "ordered_levels": flat}


def level_states(catalog: dict, completed: set, open_levels: set) -> dict:
    """level_id -> locked | available | in_progress | completed."""
    states = {}
    previous_stage_done = True
    for stage in catalog["stages"]:
        for index, level in enumerate(stage["levels"]):
            if level["id"] in completed:
                states[level["id"]] = "completed"
            elif not previous_stage_done:
                states[level["id"]] = "locked"
            elif index > 0 and stage["levels"][index - 1]["id"] not in completed:
                states[level["id"]] = "locked"
            elif level["id"] in open_levels:
                states[level["id"]] = "in_progress"
            else:
                states[level["id"]] = "available"
        previous_stage_done = all(lv["id"] in completed for lv in stage["levels"])
    return states


def next_level_id(catalog: dict, states: dict) -> Optional[str]:
    """Where "Continue Adventure" goes: an unfinished level first, otherwise the
    first open level that has not been completed. None once everything is done."""
    ordered = catalog["ordered_levels"]
    for wanted in ("in_progress", "available"):
        for level in ordered:
            if states[level["id"]] == wanted:
                return level["id"]
    return None


def stars_for(first_try_pct: float) -> int:
    for stars, minimum in sorted(STAR_THRESHOLDS.items(), reverse=True):
        if first_try_pct >= minimum:
            return stars
    return 1


def public_level(level: dict, state: str, stats: dict) -> dict:
    """A level as sent to the client -- never includes question ids or answers."""
    return {
        "id": level["id"], "stage_id": level["stage_id"], "order": level["order"], "number": level["global_order"] + 1,
        "course_id": level["course_id"], "name": level["name"], "description": level["description"],
        "question_count": level["question_count"], "formats": level["formats"],
        "completion_requirement": level["completion_requirement"], "reward": level["reward"],
        "state": state,
        "completions": stats.get("completions", 0),
        "best_first_try_pct": stats.get("best_first_try_pct"),
        "stars": stars_for(stats["best_first_try_pct"]) if stats.get("completions") else 0,
    }


def compute_progress(catalog: dict, completions: list, open_levels: set) -> dict:
    """The student's full progression view from their completion rows."""
    stats: dict = {}
    for row in completions:
        s = stats.setdefault(row["level_id"], {"completions": 0, "best_first_try_pct": 0.0})
        s["completions"] += 1
        s["best_first_try_pct"] = max(s["best_first_try_pct"], row["first_try_pct"])

    completed = set(stats)
    states = level_states(catalog, completed, open_levels)
    current = next_level_id(catalog, states)

    stages = []
    for stage in catalog["stages"]:
        levels = [public_level(lv, states[lv["id"]], stats.get(lv["id"], {})) for lv in stage["levels"]]
        done = sum(1 for lv in levels if lv["state"] == "completed")
        if done == len(levels):
            stage_state = "completed"
        elif levels[0]["state"] == "locked":
            stage_state = "locked"
        elif done or any(lv["state"] == "in_progress" for lv in levels):
            stage_state = "in_progress"
        else:
            stage_state = "available"
        stages.append({"id": stage["id"], "name": stage["name"], "description": stage["description"],
                       "theme": stage["theme"], "difficulty": stage["difficulty"], "state": stage_state, "levels_completed": done,
                       "levels_total": len(levels), "levels": levels})

    total = len(catalog["ordered_levels"])
    cleared = len(completed & set(catalog["levels"]))
    return {
        "world": catalog["world"],
        "stages": stages,
        "current_level_id": current,
        "all_completed": cleared == total and total > 0,
        "totals": {"levels_completed": cleared, "levels_total": total,
                   "quests_completed": sum(s["completions"] for s in stats.values())},
    }
