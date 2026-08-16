/**
 * Putting cover art on a shortcut.
 *
 * Steam takes bare base64 and an asset-type number, and stretches whatever it
 * is given to fill the slot -- which is why most of the work here is reshaping
 * a picture that was never the right shape to begin with.
 */
import type { ArtImage } from "../backend";
import { fitToSlot } from "../fitArtwork";
import { LibraryAssetType, sleep, steamClient } from "./client";

/** Strips the `data:image/png;base64,` prefix -- Steam wants bare base64. */
function toBareBase64(dataUri: string): string {
  const marker = ";base64,";
  const index = dataUri.indexOf(marker);
  return index === -1 ? dataUri : dataUri.slice(index + marker.length);
}

const ART_SLOTS: Array<[keyof ResolvedArt, LibraryAssetType]> = [
  ["capsule", LibraryAssetType.Capsule],
  ["header", LibraryAssetType.Header],
  ["hero", LibraryAssetType.Hero],
  ["logo", LibraryAssetType.Logo],
];

type ResolvedArt = Partial<Record<"capsule" | "header" | "hero" | "logo", ArtImage>>;

/**
 * Steam has cleared a slot some time after it says it has.
 *
 * `ClearCustomArtworkForApp` resolves immediately rather than when the asset is
 * gone, so writing the replacement straight afterwards can land before the
 * clear and be wiped by it. Half a second is what decky-steamgriddb settled on
 * for the same call, and it is paid once for the whole set rather than per slot.
 */
const CLEAR_SETTLES_MS = 500;

/**
 * Empty every slot, so what follows is the new game's artwork and nothing else.
 *
 * Two separate reasons, both seen on the device:
 *
 * A source does not necessarily fill all four. A libretro row is a boxart and
 * only a boxart, so picking one used to replace the capsule and leave the hero,
 * logo and header belonging to whichever game was identified before it -- the
 * new cover over the old backdrop, which reads as "some of the artwork did not
 * update" because that is exactly what happened.
 *
 * And Steam does not reliably refresh a slot that already holds custom art:
 * decky-steamgriddb clears before every single write, including the ones that
 * overwrite. So the clear is not only for the slots being left empty.
 */
async function clearArtwork(appId: number, apps: any): Promise<void> {
  if (!apps.ClearCustomArtworkForApp) return;

  for (const [, assetType] of ART_SLOTS) {
    try {
      await apps.ClearCustomArtworkForApp(appId, assetType);
    } catch (error) {
      // Best effort: a slot that would not clear is no worse than before, and
      // the write that follows may well succeed anyway.
      console.error(`[deckyemu] could not clear art slot ${assetType}`, error);
    }
  }

  await sleep(CLEAR_SETTLES_MS);
}

/**
 * Replaces a game's artwork with whatever we have. Returns the slots that stuck.
 *
 * A replacement, not a patch: anything not supplied is cleared rather than left
 * behind. See `clearArtwork`.
 */
export async function applyArtwork(appId: number, art: ResolvedArt): Promise<number> {
  const apps = steamClient()?.Apps;
  if (!apps?.SetCustomArtworkForApp) {
    return 0;
  }

  // Nothing to put there is not the same as "this game has no artwork". A
  // lookup that came back empty would otherwise strip a perfectly good cover
  // and leave the game worse than it found it.
  if (!ART_SLOTS.some(([slot]) => art[slot]?.data)) {
    return 0;
  }

  await clearArtwork(appId, apps);

  let applied = 0;
  for (const [slot, assetType] of ART_SLOTS) {
    const image = art[slot];
    if (!image?.data) continue;

    let data = image.data;
    let kind: string = image.kind;
    /*
     * Redrawn when it is the wrong shape for the slot. libretro's thumbnails are
     * scans of the physical box, so for most systems Steam is handed a landscape
     * or square picture for a portrait slot and stretches it -- which is what
     * makes a freshly added game look wrong next to real Steam covers.
     *
     * Never the logo: it is a transparent PNG meant to sit free-form, and
     * putting a blurred backdrop behind one would be worse than any stretching.
     *
     * Best effort. A failure here leaves the original, which is what would have
     * been used anyway.
     */
    if (slot !== "logo") {
      try {
        const fitted = await fitToSlot(image.data, slot);
        if (fitted) {
          data = fitted;
          kind = "jpg";
        }
      } catch (error) {
        console.error(`[deckyemu] could not fit ${slot} art`, error);
      }
    }

    try {
      await apps.SetCustomArtworkForApp(appId, toBareBase64(data), kind, assetType);
      applied += 1;
    } catch (error) {
      console.error(`[deckyemu] failed to set ${slot} art`, error);
    }
  }
  return applied;
}
