// Lays the world out on the map: pure geometry, no progression rules. Which
// stages and levels exist, and their states, come from the backend
// (GET /progress/me); this only decides where to draw them, so adding a level
// or stage on the server just makes the map longer.
//
// Units: the map is 100 wide; y grows downward. Each stage is a band holding
// its level nodes in a zig-zag, and the treasure chest sits below the last band.

const NODE_X = [26, 72, 28, 74];
const BAND_TOP = 30; // room for the stage banner above the first node
const NODE_GAP = 22;
const BAND_BOTTOM = 14;

export function computeLayout(stages) {
  let y = 0;
  const bands = [];
  const nodes = [];

  stages.forEach((stage) => {
    const top = y;
    const height = BAND_TOP + (stage.levels.length - 1) * NODE_GAP + BAND_BOTTOM + 6;
    stage.levels.forEach((level, index) => {
      nodes.push({ level, stage, x: NODE_X[index % NODE_X.length], y: top + BAND_TOP + index * NODE_GAP });
    });
    bands.push({ stage, top, height });
    y += height;
  });

  return { bands, nodes, chest: [50, y + 22], height: y + 44 };
}

// Smooth S-curve through consecutive points -- one SVG path.
export function pathThrough(points) {
  return points
    .map(([x, y], index) => {
      if (index === 0) return `M ${x} ${y}`;
      const [px, py] = points[index - 1];
      const midY = (py + y) / 2;
      return `C ${px} ${midY}, ${x} ${midY}, ${x} ${y}`;
    })
    .join(" ");
}
