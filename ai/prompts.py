"""
QuestVerse Groq Prompt Templates & Validation
Produces strict, parseable JSON questions matching the backend Question schema.
"""

SYSTEM_PROMPT = """You are an educational engine for QuestVerse.
Generate exactly ONE multiple-choice question in valid, raw JSON.
Never include markdown blocks (no ```json), explanations, or text outside the JSON object.

Strict JSON format:
{
  "prompt": "Clear question text",
  "options": ["Option A", "Option B", "Option C", "Option D"],
  "correct_answer": "Exact matching string from options",
  "hint": "One-sentence hint for struggling students",
  "tier": 1
}
"""

def build_user_prompt(subject: str, topic: str, tier: int) -> str:
    """Formats the input prompt for Groq inference."""
    return (
        f"Subject: {subject}\n"
        f"Topic: {topic}\n"
        f"Difficulty Tier: {tier} (1=easiest, 3=hardest)\n"
        f"Ensure all 4 options are plausible, unique, and exactly one is correct."
    )

def validate_llm_response(data: dict, expected_tier: int) -> bool:
    """Verifies that the LLM response strictly follows schema rules."""
    required_keys = {"prompt", "options", "correct_answer", "hint", "tier"}
    if not required_keys.issubset(data.keys()):
        return False
    if not isinstance(data["options"], list) or len(data["options"]) != 4:
        return False
    if len(set(data["options"])) != 4:
        return False
    if data["correct_answer"] not in data["options"]:
        return False
    return True 
