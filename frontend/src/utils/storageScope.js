// Browser-side saves (hero XP, achievements, last hero...) belong to the logged-in user, so two
// people sharing a browser never see each other's data. The scope is set once at login/logout.
let scope = "";

export function setStorageScope(userId) {
  scope = userId ? `:u${userId}` : "";
}

export const scoped = (key) => `${key}${scope}`;
