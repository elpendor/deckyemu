/**
 * Fitting artwork to the shape Steam draws it in.
 *
 * libretro's thumbnails are scans of the physical box, and a box is whatever
 * shape that console's boxes were. Steam's cover slot is 600x900. Measured
 * against the real thumbnails:
 *
 *     SNES        512 x 357   landscape   115% off
 *     N64         512 x 357   landscape   115% off
 *     PlayStation 512 x 512   square       50% off
 *     Game Boy Advance 512 x 512  square   50% off
 *     Mega Drive  512 x 720   0.71          7% off
 *
 * So for most systems a *landscape or square* image is handed to a portrait
 * slot, and Steam stretches it. That is the wrong-looking artwork; it is not a
 * matter of resolution.
 *
 * Cropping is not the answer -- trimming 512x357 to 2:3 would discard two thirds
 * of the width, title and all. The image is drawn at its true proportions and
 * centred instead, with the leftover space filled by a blurred copy of itself.
 *
 * Everything here is geometry and thresholds. The drawing lives next to it in
 * `fitArtwork`, which needs a canvas and therefore cannot be tested.
 */

/** What Steam expects in each slot, in pixels. */
export const SLOT_SIZE = {
  capsule: { width: 600, height: 900 },
  header: { width: 460, height: 215 },
  hero: { width: 1920, height: 620 },
} as const;

export type FittableSlot = keyof typeof SLOT_SIZE;

/**
 * How far apart two aspect ratios are, as a fraction of the target.
 *
 * Ratios rather than dimensions: a 512x357 and a 1024x714 are the same picture
 * as far as this is concerned.
 */
export function aspectDrift(width: number, height: number, slot: FittableSlot): number {
  const size = SLOT_SIZE[slot];
  if (!(width > 0) || !(height > 0)) return 0;
  const target = size.width / size.height;
  return Math.abs(width / height - target) / target;
}

/**
 * Above this, stretching is visible and worth fixing; below it, bars are worse.
 *
 * 12% keeps Mega Drive's 7% passing straight through -- stretching that by a
 * fifteenth is invisible, while letterboxing it would add bars for nothing --
 * and catches the square and landscape cases, which start at 50%.
 */
export const DRIFT_TOLERANCE = 0.12;

/**
 * Whether this image should be redrawn rather than handed over as it is.
 *
 * Driven by the measurement, never by which source the art came from. Artwork
 * made for Steam arrives at the right shape and passes through untouched
 * whoever produced it, and a box scan gets fixed whoever produced it.
 */
export function needsFitting(width: number, height: number, slot: FittableSlot): boolean {
  if (!(width > 0) || !(height > 0)) return false;
  return aspectDrift(width, height, slot) > DRIFT_TOLERANCE;
}

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * Where to draw `width x height` inside the slot, whole and centred.
 *
 * Contain rather than cover: nothing may be cropped, because what would be
 * cropped from a boxart is the title.
 */
export function containRect(width: number, height: number, slot: FittableSlot): Rect {
  const size = SLOT_SIZE[slot];
  if (!(width > 0) || !(height > 0)) {
    return { x: 0, y: 0, width: size.width, height: size.height };
  }

  const scale = Math.min(size.width / width, size.height / height);
  const drawn = { width: Math.round(width * scale), height: Math.round(height * scale) };
  return {
    x: Math.round((size.width - drawn.width) / 2),
    y: Math.round((size.height - drawn.height) / 2),
    width: drawn.width,
    height: drawn.height,
  };
}

/**
 * Where to draw the blurred backdrop: the same image, scaled to *cover*.
 *
 * Cover rather than contain, or the backdrop would have gaps of its own. It is
 * overscanned a little as well, because a blur samples past its edges and would
 * otherwise fade to transparent at the border.
 */
export function backdropRect(width: number, height: number, slot: FittableSlot): Rect {
  const size = SLOT_SIZE[slot];
  const overscan = 1.15;
  if (!(width > 0) || !(height > 0)) {
    return { x: 0, y: 0, width: size.width, height: size.height };
  }

  const scale = Math.max(size.width / width, size.height / height) * overscan;
  const drawn = { width: Math.round(width * scale), height: Math.round(height * scale) };
  return {
    x: Math.round((size.width - drawn.width) / 2),
    y: Math.round((size.height - drawn.height) / 2),
    width: drawn.width,
    height: drawn.height,
  };
}
