import explorerSprite from "./assets/mascot-correct.png";

// Playable characters. "human" keeps the original walking-explorer sprite
// image; the rest are emoji-based since there's no other sprite art in the
// project -- consistent with how Frontpage/Dashboard already use plain
// emoji/unicode as iconography rather than custom art.
export const CHARACTERS = [
  {
    id: "human",
    label: "Explorer",
    blurb: "A seasoned adventurer, ready for anything.",
    spriteType: "image",
    spriteSrc: explorerSprite,
  },
  {
    id: "zombie",
    label: "Zombie",
    blurb: "Slow, relentless, and surprisingly sharp on quiz night.",
    spriteType: "emoji",
    spriteValue: "🧟",
  },
  {
    id: "spaceship",
    label: "Spaceship",
    blurb: "Cruises through questions at light speed.",
    spriteType: "emoji",
    spriteValue: "🚀",
  },
  {
    id: "robot",
    label: "Robot",
    blurb: "Calculated, precise, never forgets a fact.",
    spriteType: "emoji",
    spriteValue: "🤖",
  },
];

export function getCharacter(characterId) {
  return CHARACTERS.find((character) => character.id === characterId) ?? CHARACTERS[0];
}
