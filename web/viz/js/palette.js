// Greyscale terrain (the world is black and white until a seat thinks about it), vivid seat hues, glyphs.
export const TERRAIN_GREY = { O: "#141821", C: "#1f2530", L: "#20262f", G: "#5a5f66", P: "#66696d", D: "#7d7b76",
                              T: "#4c4f55", S: "#9a9ea6", "?": "#333" };
export const MOUNTAIN = "#c9ccd2";
export const HILLS = "#7b7f88";

// The feature legend names come from GameInfo.Features minus FEATURE_; unknown names get no glyph.
export const FEATURE_GLYPH = { FOREST: "♣", JUNGLE: "♠", MARSH: "≈", OASIS: "●", ICE: "❄", FLOOD_PLAINS: "≡",
                               FALLOUT: "☢", ATOLL: "◌" };
export const NATURAL_WONDER = "★";      // any feature not in the table but with a wonder-like name

// Attention hues by seat *index* (order seats were first seen), not player id: two seats must never look alike.
export const SEAT_HUES = ["#ff7a3d", "#3fb0ff", "#c6ff3d", "#ff3fd0", "#ffd43d", "#3dffd9", "#b48cff", "#ff5c5c"];

export function rgb(c, fallback = "#888") {
  return Array.isArray(c) && c.length === 3 ? `rgb(${c[0]},${c[1]},${c[2]})` : fallback;
}

export function featureGlyph(name) {
  if (!name) return "";
  if (FEATURE_GLYPH[name]) return FEATURE_GLYPH[name];
  return /^(CRATER|FUJI|MESA|REEF|VOLCANO|GIBRALTAR|GEYSER|FOUNTAIN|POTOSI|EL_DORADO|SRI_PADA|MT_|KAILASH|ULURU|LAKE_VICTORIA|KILIMANJARO|SOLOMONS|SINAI)/.test(name)
    ? NATURAL_WONDER : "";
}

export function unitGlyph(u) {
  if (u.civ) return u.t && /SETTLER/.test(u.t) ? "⌂" : "•";
  if (u.d === "S") return "⛵";
  if (u.d === "A") return "✈";
  return u.t ? u.t[0] : "?";
}
