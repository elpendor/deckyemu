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

/** One slot's picture, reshaped and ready for Steam. */
interface Ready {
  slot: keyof ResolvedArt;
  assetType: LibraryAssetType;
  data: string;
  kind: string;
}

/**
 * Reshape everything before Steam is touched at all.
 *
 * The order is the point. Fitting decodes and redraws a picture on a canvas,
 * which for a 4K hero is the slowest thing in here by far -- and while it runs,
 * the slot it is destined for must still hold the *old* game's art rather than
 * nothing. Clearing first and fitting afterwards is what made a game details
 * page sit empty for seconds; see `applyArtwork`.
 */
async function fitAll(art: ResolvedArt): Promise<{ ready: Ready[]; abandoned: LibraryAssetType[] }> {
  const ready: Ready[] = [];
  const abandoned: LibraryAssetType[] = [];

  for (const [slot, assetType] of ART_SLOTS) {
    const image = art[slot];
    if (!image?.data) {
      abandoned.push(assetType);
      continue;
    }

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

    ready.push({ slot, assetType, data, kind });
  }

  return { ready, abandoned };
}

/**
 * Replaces a game's artwork with whatever we have. Returns the slots that stuck.
 *
 * A replacement, not a patch: anything not supplied is cleared rather than left
 * behind, because a source does not necessarily fill all four. A libretro row is
 * a boxart and only a boxart, so filling the capsule and leaving the rest gives
 * the new cover over the old game's backdrop.
 *
 * **Nothing here may leave a slot empty for longer than one write takes.** A
 * game details page open behind the editor renders the artwork straight off
 * these files, and it renders their absence just as promptly: Steam's custom art
 * URL is `/customimages/<appid><suffix>.<ext>?v=<rt_custom_image_mtime>`, and
 * `BHasCustomImages()` is `rt_custom_image_mtime > 0`, so an app with every slot
 * cleared offers no URLs at all and the page goes blank. Worse, the hero and the
 * logo do not recover the same way afterwards -- the hero's element survives and
 * follows the new URL, but the logo's is dropped from the page and only comes
 * back when the page is re-opened. That asymmetry is what "the artwork comes
 * back if I leave and return" was.
 *
 * So the sequence is: reshape everything first, then per slot clear and write
 * back to back, then empty the abandoned slots last. Measured on the device over
 * 165 samples of a details page during six of these runs: not one sample had the
 * app without custom artwork, and not one had `rt_custom_image_mtime` unset.
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

  const { ready, abandoned } = await fitAll(art);

  let applied = 0;
  for (const { slot, assetType, data, kind } of ready) {
    /*
     * Cleared immediately before its own write, not as part of an up-front
     * sweep, and with nothing in between.
     *
     * The clear is still here, but not for the reason it used to say. Writing
     * over a slot that already holds custom art works: measured on the device,
     * a hero replaced in place went from 1427835 bytes to 131638 with no clear
     * at all. What the clear is for is the extension. Steam keeps
     * `<appid>_hero.jpg` and `<appid>_hero.png` as separate files and
     * `GetCustomImageURLs` offers jpg first, so a png written over a slot
     * holding a jpg leaves the jpg winning -- the previous game's art, on the
     * new game, indefinitely. Clearing drops both extensions, which was
     * measured too.
     *
     * Best effort: a slot that would not clear is no worse than before, and the
     * write that follows may well succeed anyway.
     */
    if (apps.ClearCustomArtworkForApp) {
      try {
        await apps.ClearCustomArtworkForApp(appId, assetType);
      } catch (error) {
        console.error(`[deckyemu] could not clear art slot ${assetType}`, error);
      }
    }

    try {
      await apps.SetCustomArtworkForApp(appId, toBareBase64(data), kind, assetType);
      applied += 1;
    } catch (error) {
      console.error(`[deckyemu] failed to set ${slot} art`, error);
    }
  }

  /*
   * Last, once the new artwork is in place. These are the slots the new game has
   * nothing for, so they end up genuinely empty either way -- but doing them
   * after the writes means the page is never showing *nothing*, only the slots
   * that are honestly missing.
   */
  if (apps.ClearCustomArtworkForApp) {
    for (const assetType of abandoned) {
      try {
        await apps.ClearCustomArtworkForApp(appId, assetType);
      } catch (error) {
        console.error(`[deckyemu] could not clear art slot ${assetType}`, error);
      }
    }
  }

  return applied;
}
