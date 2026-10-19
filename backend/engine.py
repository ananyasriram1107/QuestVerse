def next_state(tier: int, correct_streak: int, wrong_streak: int, correct: bool) -> dict:
    """
    Pure function: given the current adaptive state and whether the last
    answer was correct, returns the new state. No HTTP, no I/O — just math,
    so it's trivial to test in isolation.
    """
    if correct:
        correct_streak += 1
        wrong_streak = 0
        xp_earned = tier * 10

        if correct_streak >= 2:
            tier = min(3, tier + 1)   # bump difficulty, capped at tier 3
            correct_streak = 0         # reset so the NEXT bump needs 2 more
    else:
        wrong_streak += 1
        correct_streak = 0
        xp_earned = 0

        if wrong_streak >= 2:
            tier = max(1, tier - 1)   # ease difficulty, floored at tier 1
            wrong_streak = 0

    return {
        "tier": tier,
        "correct_streak": correct_streak,
        "wrong_streak": wrong_streak,
        "xp_earned": xp_earned,
    }


def level_from_xp(total_xp: int) -> int:
    """Simple RPG-style level curve: 0xp=L1, 50xp=L2, 200xp=L3, 450xp=L4..."""
    return int((total_xp / 50) ** 0.5) + 1

# Number of questions that must be SOLVED to finish a quest. Mirrors
# frontend/src/questConfig.js; the backend is the authority on completion.
QUEST_LENGTH = 5
