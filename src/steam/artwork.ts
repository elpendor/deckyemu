/**
 * Putting cover art on a shortcut.
 *
 * Steam takes bare base64 and an asset-type number, and stretches whatever it
 * is given to fill the slot -- which is why most of the work here is reshaping
 * a picture that was never the right shape to begin with.
 */
import type { ArtImage } from "../backend";
import { fitToSlot } from "../fitArtwork";
import { appStore, LibraryAssetType, sleep, steamClient } from "./client";

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
 * Long enough to be sure the clock has turned over, and to spare.
 *
 * `Date.now() % 1000` says how far into the current second we are; the wait is
 * the rest of it plus this. Steam's own publish of the change lags the write by
 * about 100 ms, measured, and that lag is on the right side -- the file is
 * complete before the page is told -- so this margin only has to cover the
 * turnover itself.
 */
const NEXT_SECOND_MARGIN_MS = 250;

/**
 * Write one slot again, in a later second than everything before it.
 *
 * This exists because of what the version token in the URL actually is.
 * `rt_custom_image_mtime` is an mtime **in whole seconds**, and it is the only
 * thing that changes the URL of every slot at once. Four writes inside one
 * second therefore produce one single token: the page re-renders on the first
 * change, fetches all four URLs at that instant, and then never re-fetches,
 * because no later write moves the token. Whatever it caught mid-sequence is
 * what it keeps -- a slot cleared but not yet rewritten is a blank, and a slot
 * not yet reached still serves the previous game's picture.
 *
 * That is the whole of "sometimes it refreshes and sometimes it doesn't": it
 * depends on nothing more than whether the writes happened to straddle a second
 * boundary. Measured on the device, with the token values in hand: capsule and
 * header landed in second 7503, the hero's clear moved the token to 7504 and the
 * page re-rendered there -- backdrop already deleted, logo still the old file --
 * and the hero's write and the logo's clear and write all landed inside 7504 too,
 * so the page was never told again.
 *
 * So: once every file is final, wait for the clock to turn and write one of them
 * a second time. The bytes are identical, so nothing moves on screen except the
 * token, and one clean re-render puts the whole set on screen at once. The
 * cheapest slot is chosen because the only cost that matters here is the size of
 * the base64 crossing to Steam.
 */
async function republish(appId: number, apps: any, written: Ready[]): Promise<void> {
  const cheapest = written.reduce((best, slot) => (slot.data.length < best.data.length ? slot : best));

  await sleep(1000 - (Date.now() % 1000) + NEXT_SECOND_MARGIN_MS);

  try {
    // Deliberately no clear. A clear here would delete the file to write it back
    // again, which is exactly the gap this whole function exists to close.
    await apps.SetCustomArtworkForApp(
      appId,
      toBareBase64(cheapest.data),
      cheapest.kind,
      cheapest.assetType,
    );
  } catch (error) {
    // The artwork is already on disk and correct; all that is lost is the
    // re-render, which re-opening the page would have done anyway.
    console.error("[deckyemu] could not republish artwork", error);
  }
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

  // Last of all, and only if something was written: one more token, in a second
  // of its own, so a page already on screen re-reads the finished set. See
  // `republish` -- without it the page keeps whatever it saw mid-sequence.
  if (applied > 0) {
    await republish(appId, apps, ready);
  }

  return applied;
}


/**
 * A URL for the landscape art already on a shortcut, or "".
 *
 * The read side of everything above, and the only one there is: nothing writes
 * these files but this plugin, and nothing else can read them back either --
 * they live under Steam's own userdata and a panel cannot open a file. What
 * `appStore` hands out is a `/customimages/<appid>.jpg?v=<stamp>` address the
 * client already serves, which an `<img>` can use directly.
 *
 * **Landscape rather than the vertical capsule**, which is the other thing
 * written. A capsule is 600x900, so at the height of a list row it comes out
 * about thirty pixels wide -- a sliver nobody could recognise a game from. The
 * header is 460x215 and drawn to be read small.
 *
 * The version stamp on the end is Steam's, and it is why replacing a game's
 * artwork updates a list already on screen: the address changes with the
 * picture, so nothing has to be told to refresh.
 *
 * **Every candidate, not the first one.** Steam returns one URL per file
 * extension it might have been saved under, and only one of them exists: the
 * art this plugin writes lands as `<appid>.png` while the first URL offered
 * asks for `<appid>.jpg`, which 404s. Taking `[0]` produced a list of broken
 * images. The caller tries them in order, which is what the array is for.
 *
 * Returns [] for every way this can come to nothing -- no store, a shortcut the
 * store has not registered, a game whose artwork lookup found nothing at the
 * time it was added. All three are ordinary, so none of them is logged.
 */
export function landscapeArtUrls(appId: number): string[] {
  try {
    const store = appStore();
    const overview = store?.GetAppOverviewByAppID?.(appId);
    if (!overview) return [];
    // Steam's own spelling, not a typo here: `GetCustomLandcapeImageURLs`.
    const urls = store.GetCustomLandcapeImageURLs?.(overview);
    return Array.isArray(urls) ? urls.map(String).filter(Boolean) : [];
  } catch {
    return [];
  }
}
