export default function AchievementsToggle({ onClick }) {
  return (
    <button
      type="button"
      className="achievements-toggle"
      onClick={onClick}
      aria-label="View achievements"
      title="Achievements"
    >
      🏆
    </button>
  );
}
