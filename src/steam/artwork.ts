/**
 * Putting cover art on a shortcut.
 *
 * Steam takes bare base64 and an asset-type number, and stretches whatever it
 * is given to fill the slot -- which is why most of the work here is reshaping
 * a picture that was never the right shape to begin with.
 */
import type { ArtImage } from "../backend";
import { fitToSlot } from "../fitArtwork";
import { LibraryAssetType, steamClient } from "./client";

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

/** Applies whatever art we have. Returns the number of slots that stuck. */
export async function applyArtwork(appId: number, art: ResolvedArt): Promise<number> {
  const apps = steamClient()?.Apps;
  if (!apps?.SetCustomArtworkForApp) {
    return 0;
  }

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
