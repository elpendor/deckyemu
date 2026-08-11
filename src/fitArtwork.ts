import { backdropRect, containRect, needsFitting, SLOT_SIZE, type FittableSlot } from "./capsuleFit";

/**
 * Redraw artwork that is the wrong shape for the slot Steam puts it in.
 *
 * The geometry and the reasoning are in `capsuleFit`; this is the part that
 * needs a canvas and so cannot be tested. Kept as thin as possible for that
 * reason -- every decision it makes is made next door.
 *
 * Done here rather than in the backend because the backend is stdlib-only on
 * decky's frozen Python: there is no Pillow and there will not be one. The
 * browser already has everything needed.
 */

/** How much to blur the backdrop, at capsule scale. */
const BLUR_PX = 28;
/** Darkened so the real cover reads as the subject rather than one of two. */
const BACKDROP_DIM = 0.45;

function loadImage(dataUri: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("the image could not be decoded"));
    image.src = dataUri;
  });
}

/**
 * `dataUri` redrawn to fill `slot`, or null when it does not need it.
 *
 * Null rather than the original, so the caller can tell "nothing to do" from
 * "done" and skip re-encoding a picture that was already right.
 */
export async function fitToSlot(dataUri: string, slot: FittableSlot): Promise<string | null> {
  const image = await loadImage(dataUri);
  const width = image.naturalWidth;
  const height = image.naturalHeight;
  if (!needsFitting(width, height, slot)) return null;

  const size = SLOT_SIZE[slot];
  const canvas = document.createElement("canvas");
  canvas.width = size.width;
  canvas.height = size.height;
  const context = canvas.getContext("2d");
  if (!context) return null;

  // The backdrop: the same picture, covering the slot, blurred and dimmed. A
  // flat colour would read as a broken image; this reads as a deliberate frame.
  const behind = backdropRect(width, height, slot);
  context.filter = `blur(${BLUR_PX}px)`;
  context.drawImage(image, behind.x, behind.y, behind.width, behind.height);
  context.filter = "none";
  context.fillStyle = `rgba(0, 0, 0, ${BACKDROP_DIM})`;
  context.fillRect(0, 0, size.width, size.height);

  // Then the cover itself, whole and centred.
  const front = containRect(width, height, slot);
  context.drawImage(image, front.x, front.y, front.width, front.height);

  // JPEG, not PNG: a 600x900 photographic capsule is several times larger as a
  // PNG and every byte goes through the websocket to Steam. Nothing here has
  // transparency to lose -- the backdrop is opaque by construction.
  return canvas.toDataURL("image/jpeg", 0.92);
}
