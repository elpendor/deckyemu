import { describe, expect, it } from "vitest";

import {
  aspectDrift,
  backdropRect,
  containRect,
  needsFitting,
  SLOT_SIZE,
} from "./capsuleFit";

/*
 * The dimensions are real: read from thumbnails.libretro.com by fetching the
 * first 24 bytes of each PNG and unpacking the IHDR. They are the reason this
 * module exists, so they are the cases it is checked against rather than
 * round numbers chosen to be convenient.
 */
const REAL = {
  snes: { width: 512, height: 357 },
  n64: { width: 512, height: 357 },
  playstation: { width: 512, height: 512 },
  gba: { width: 512, height: 512 },
  megadrive: { width: 512, height: 720 },
  /** What SteamGridDB serves: authored for the slot. */
  sgdbGrid: { width: 600, height: 900 },
};

describe("needsFitting", () => {
  it("catches a landscape box scan in a portrait slot", () => {
    // The worst case and the most common: SNES and N64 boxes are wider than
    // they are tall, and the cover slot is half again taller than it is wide.
    expect(needsFitting(REAL.snes.width, REAL.snes.height, "capsule")).toBe(true);
    expect(needsFitting(REAL.n64.width, REAL.n64.height, "capsule")).toBe(true);
  });

  it("catches a square box scan", () => {
    expect(needsFitting(REAL.playstation.width, REAL.playstation.height, "capsule")).toBe(true);
    expect(needsFitting(REAL.gba.width, REAL.gba.height, "capsule")).toBe(true);
  });

  /*
   * Mega Drive boxes are tall, so their scans are already close to the slot.
   * Stretching by a fifteenth is invisible; bars either side of it are not, so
   * the near-misses have to pass through untouched.
   */
  it("leaves a shape that is already close enough alone", () => {
    expect(needsFitting(REAL.megadrive.width, REAL.megadrive.height, "capsule")).toBe(false);
    expect(aspectDrift(REAL.megadrive.width, REAL.megadrive.height, "capsule")).toBeLessThan(0.1);
  });

  // The rule is about measurements, not about which service produced the file.
  it("passes art already made for the slot straight through", () => {
    expect(needsFitting(REAL.sgdbGrid.width, REAL.sgdbGrid.height, "capsule")).toBe(false);
    expect(needsFitting(1200, 1800, "capsule")).toBe(false);
    expect(needsFitting(460, 215, "header")).toBe(false);
    expect(needsFitting(1920, 620, "hero")).toBe(false);
  });

  // Nothing is known about a picture with no size, and redrawing it blind
  // would turn an unknown into a definitely-wrong one.
  it("does nothing when the size is not known", () => {
    for (const [w, h] of [[0, 0], [512, 0], [0, 512], [-1, 5], [NaN, NaN]]) {
      expect(needsFitting(w, h, "capsule")).toBe(false);
    }
  });
});

describe("containRect", () => {
  it("keeps the whole image, at its true proportions", () => {
    const rect = containRect(REAL.snes.width, REAL.snes.height, "capsule");
    // Cropping is what must not happen: what gets cropped off a boxart is the
    // title, so it fits inside the slot rather than filling it.
    expect(rect.width).toBeLessThanOrEqual(SLOT_SIZE.capsule.width);
    expect(rect.height).toBeLessThanOrEqual(SLOT_SIZE.capsule.height);
    const before = REAL.snes.width / REAL.snes.height;
    expect(rect.width / rect.height).toBeCloseTo(before, 2);
  });

  it("centres what is left over", () => {
    const rect = containRect(REAL.snes.width, REAL.snes.height, "capsule");
    expect(rect.x * 2 + rect.width).toBeCloseTo(SLOT_SIZE.capsule.width, 0);
    expect(rect.y * 2 + rect.height).toBeCloseTo(SLOT_SIZE.capsule.height, 0);
  });

  it("touches one pair of edges, so nothing is scaled down needlessly", () => {
    // A landscape image in a portrait slot is limited by width.
    const wide = containRect(REAL.snes.width, REAL.snes.height, "capsule");
    expect(wide.width).toBe(SLOT_SIZE.capsule.width);
    expect(wide.height).toBeLessThan(SLOT_SIZE.capsule.height);

    // A very tall one is limited by height.
    const tall = containRect(400, 2000, "capsule");
    expect(tall.height).toBe(SLOT_SIZE.capsule.height);
    expect(tall.width).toBeLessThan(SLOT_SIZE.capsule.width);
  });

  it("fills the slot exactly when the shape already matches", () => {
    const rect = containRect(REAL.sgdbGrid.width, REAL.sgdbGrid.height, "capsule");
    expect(rect).toEqual({ x: 0, y: 0, width: 600, height: 900 });
  });
});

describe("backdropRect", () => {
  /*
   * The backdrop covers rather than contains, or it would have gaps of its own
   * and the fix would look like the bug. Overscanned as well, because a blur
   * samples past the edges and would fade out at the border otherwise.
   */
  it("covers the whole slot with room to spare", () => {
    for (const size of Object.values(REAL)) {
      const rect = backdropRect(size.width, size.height, "capsule");
      expect(rect.x).toBeLessThanOrEqual(0);
      expect(rect.y).toBeLessThanOrEqual(0);
      expect(rect.x + rect.width).toBeGreaterThanOrEqual(SLOT_SIZE.capsule.width);
      expect(rect.y + rect.height).toBeGreaterThanOrEqual(SLOT_SIZE.capsule.height);
    }
  });

  it("keeps the backdrop's proportions too, so it is not a stretched smear", () => {
    const rect = backdropRect(REAL.snes.width, REAL.snes.height, "capsule");
    expect(rect.width / rect.height).toBeCloseTo(REAL.snes.width / REAL.snes.height, 2);
  });

  it("falls back to the whole slot when the size is unknown", () => {
    expect(backdropRect(0, 0, "capsule")).toEqual({ x: 0, y: 0, width: 600, height: 900 });
  });
});
