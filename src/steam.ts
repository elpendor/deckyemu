/**
 * Everything that talks to the Steam client.
 *
 * These are undocumented internal APIs, so each one is called defensively and
 * the shapes are declared locally rather than imported -- a Steam update that
 * renames a method should degrade the feature, not break the whole plugin.
 */

import type { ArtImage } from "./backend";
import { fitToSlot } from "./fitArtwork";

/** Matches ELibraryAssetType in decky-frontend-lib / generated Steam types. */
export const enum LibraryAssetType {
  Capsule = 0,
  Hero = 1,
  Logo = 2,
  Header = 3,
  Icon = 4,
  HeroBlur = 5,
}

interface AppOverview {
  appid: number;
  display_name?: string;
  /** Steam's 64-bit GameID as a string. RunGame wants this, not the appid. */
  gameid?: string;
}

interface Collection {
  AsDragDropCollection: () => {
    AddApps: (overviews: AppOverview[]) => void;
    RemoveApps: (overviews: AppOverview[]) => void;
  };
  Save: () => Promise<void>;
  apps: { has: (appId: number) => boolean };
  displayName: string;
}

interface CollectionStore {
  /**
   * Sometimes a Map, sometimes an array, depending on the Steam build -- always
   * read it through `allCollections()` rather than iterating it directly.
   */
  userCollections: Collection[] | Map<string, Collection>;
  GetCollection: (collectionId: string) => Collection | undefined;
  GetCollectionIDByUserTag: (tag: string) => string | null;
  NewUnsavedCollection: (
    tag: string,
    filter: unknown | undefined,
    overviews: AppOverview[],
  ) => Collection | undefined;
}

interface CollectionExtras {
  Delete: () => Promise<void>;
  allApps: AppOverview[];
}

// `any` deliberately: these are undocumented globals the Steam client injects.
// There is nothing to import types from, and their shape changes between builds
// -- the interfaces above describe only the parts this file actually uses, which
// is why every call site checks for the method before calling it.
const steamClient = (): any => (window as any).SteamClient;
const appStore = (): any => (window as any).appStore;
const collectionStore = (): CollectionStore | null =>
  (window as any).collectionStore ?? null;

/** Strips the `data:image/png;base64,` prefix -- Steam wants bare base64. */
function toBareBase64(dataUri: string): string {
  const marker = ";base64,";
  const index = dataUri.indexOf(marker);
  return index === -1 ? dataUri : dataUri.slice(index + marker.length);
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export interface CreateShortcutArgs {
  title: string;
  exe: string;
  startDir: string;
  launchOptions: string;
}

/**
 * Creates the non-Steam shortcut and returns its appId.
 *
 * Current Steam clients accept all four AddShortcut arguments but only
 * reliably act on the first two -- it does not even set the name dependably.
 * The fields therefore have to be applied afterwards with the explicit
 * setters, and those only stick once Steam has registered the new app in
 * appStore. Both quirks are load-bearing here, not defensive padding.
 */
export async function createShortcut(args: CreateShortcutArgs): Promise<number> {
  const apps = steamClient()?.Apps;
  if (!apps?.AddShortcut) {
    throw new Error("SteamClient.Apps.AddShortcut is unavailable.");
  }

  const appId: number = await apps.AddShortcut(args.title, args.exe, "", "");

  if (typeof appId !== "number" || appId <= 0) {
    throw new Error("Steam did not return an app id for the new shortcut.");
  }

  if (!(await waitForOverview(appId))) {
    console.warn("[retroarch] app overview never appeared; applying fields anyway");
  }

  try {
    apps.SetShortcutName?.(appId, args.title);
    apps.SetShortcutExe?.(appId, args.exe);
    apps.SetShortcutStartDir?.(appId, args.startDir);
    apps.SetShortcutLaunchOptions?.(appId, args.launchOptions);
  } catch (error) {
    console.error("[retroarch] could not apply shortcut fields", error);
    throw new Error("Steam created the shortcut but rejected its settings.");
  }

  return appId;
}

export function removeShortcut(appId: number): void {
  try {
    steamClient()?.Apps?.RemoveShortcut?.(appId);
  } catch (error) {
    console.error("[retroarch] RemoveShortcut failed", error);
  }
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
      console.error(`[retroarch] failed to set ${slot} art`, error);
    }
  }
  return applied;
}

/** A freshly added shortcut takes a moment to appear in appStore. */
async function waitForOverview(appId: number, attempts = 12): Promise<AppOverview | null> {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const overview = appStore()?.GetAppOverviewByAppID?.(appId);
    if (overview) return overview as AppOverview;
    await sleep(250);
  }
  return null;
}

/**
 * Every user collection, regardless of how Steam is storing them.
 *
 * `userCollections` is a Map on some Steam builds and an array on others.
 * Iterating it directly with for..of yields [key, value] pairs for a Map, so
 * `displayName` comes back undefined and nothing matches. Both types expose
 * `.values()`, so going through that works either way.
 */
function allCollections(): Collection[] {
  const store = collectionStore();
  const raw = store?.userCollections;
  if (!raw) return [];
  try {
    const iterable = raw as { values?: () => IterableIterator<Collection> };
    if (typeof iterable.values === "function") {
      return Array.from(iterable.values());
    }
    return Array.isArray(raw) ? raw : [];
  } catch (error) {
    console.error("[retroarch] could not enumerate collections", error);
    return [];
  }
}

function findCollection(tag: string): Collection | undefined {
  const store = collectionStore();
  if (!store) return undefined;
  const id = store.GetCollectionIDByUserTag(tag);
  return typeof id === "string" ? store.GetCollection(id) : undefined;
}

async function getOrCreateCollection(tag: string): Promise<Collection | undefined> {
  const store = collectionStore();
  if (!store) return undefined;

  const existing = findCollection(tag);
  if (existing) return existing;

  const created = store.NewUnsavedCollection(tag, undefined, []);
  if (!created) return undefined;
  await created.Save();
  return created;
}

/**
 * Overviews for `appIds`, waiting for any that Steam has not registered yet.
 *
 * Waited for together rather than one after another. The wait is Steam's own
 * bookkeeping catching up, which it does for every app at once, so serialising it
 * charged a second per app that was not ready yet -- and a collection rename hands
 * this the entire library at once.
 */
async function overviewsFor(appIds: number[]): Promise<AppOverview[]> {
  const settled = await Promise.all(appIds.map((appId) => waitForOverview(appId, 4)));

  const overviews: AppOverview[] = [];
  settled.forEach((overview, index) => {
    if (overview) overviews.push(overview);
    else console.warn(`[retroarch] no app overview for ${appIds[index]}`);
  });
  return overviews;
}

/**
 * Files games under a user collection so they are grouped in Big Picture
 * instead of being lost among every other non-Steam shortcut.
 */
export async function addAppsToCollection(tag: string, appIds: number[]): Promise<boolean> {
  if (!tag || appIds.length === 0) return true;

  try {
    const collection = await getOrCreateCollection(tag);
    if (!collection) return false;

    const missing = appIds.filter((appId) => !collection.apps.has(appId));
    if (missing.length === 0) return true;

    const overviews = await overviewsFor(missing);
    if (overviews.length === 0) return false;

    collection.AsDragDropCollection().AddApps(overviews);
    await collection.Save();
    return true;
  } catch (error) {
    console.error("[retroarch] addAppsToCollection failed", error);
    return false;
  }
}

export async function addToCollection(appId: number, tag: string): Promise<boolean> {
  return addAppsToCollection(tag, [appId]);
}

/**
 * Takes games out of a collection, and deletes the collection if we emptied it.
 *
 * The delete is deliberately conditional: the user may have dragged their own
 * games in, and removing a collection that still holds them would be
 * destructive.
 */
export async function removeAppsFromCollection(
  tag: string,
  appIds: number[],
): Promise<boolean> {
  if (!tag || appIds.length === 0) return true;

  try {
    const collection = findCollection(tag);
    if (!collection) return true;

    const present = appIds.filter((appId) => collection.apps.has(appId));
    if (present.length > 0) {
      const overviews = await overviewsFor(present);
      if (overviews.length > 0) {
        collection.AsDragDropCollection().RemoveApps(overviews);
        await collection.Save();
      }
    }

    const extras = collection as unknown as CollectionExtras;
    const remaining = extras.allApps?.length ?? 1;
    if (remaining === 0 && typeof extras.Delete === "function") {
      await extras.Delete();
      console.log(`[retroarch] deleted now-empty collection "${tag}"`);
    }
    return true;
  } catch (error) {
    console.error("[retroarch] removeAppsFromCollection failed", error);
    return false;
  }
}

export interface StaleCollection {
  tag: string;
  appIds: number[];
}

/**
 * Collections holding our games that those games no longer belong to.
 *
 * Needed because games added by an older build did not record their collection,
 * so a rename could not know where to remove them from and left the old
 * collection populated. Rather than guessing a name, this looks at what Steam
 * actually contains.
 *
 * Only collections holding a game we registered are considered, and the caller
 * is expected to show the list for confirmation before anything is removed --
 * one of these could be a collection the user curates by hand.
 */
export function findStaleCollections(
  targets: Record<string, string>,
): StaleCollection[] {
  const store = collectionStore();
  if (!store) return [];

  const stale: StaleCollection[] = [];
  try {
    for (const collection of allCollections()) {
      const tag = collection.displayName;
      if (!tag) continue;

      const misplaced: number[] = [];
      for (const [appIdText, target] of Object.entries(targets)) {
        const appId = Number(appIdText);
        if (!appId || tag === target) continue;
        if (collection.apps?.has?.(appId)) misplaced.push(appId);
      }

      if (misplaced.length > 0) stale.push({ tag, appIds: misplaced });
    }
  } catch (error) {
    console.error("[retroarch] findStaleCollections failed", error);
  }

  return stale;
}

/**
 * Collections this plugin made that now hold nothing.
 *
 * A collection is emptied as its last game leaves, but only where something was
 * there to notice. Remove a shortcut in Steam itself, or use a build from
 * before removal did this, and the shelf stays in the library with nothing on
 * it -- and by then no registered game names it, so it cannot be found the way
 * every other collection here is found.
 *
 * `matches` decides ours from the user's own, and is built from the same
 * template the name was made with. Nothing that fails it is touched, however
 * empty: an empty collection somebody made by hand is theirs to keep.
 */
export function findEmptyCollections(matches: (name: string) => boolean): string[] {
  const store = collectionStore();
  if (!store) return [];

  const empty: string[] = [];
  try {
    for (const collection of allCollections()) {
      const tag = collection.displayName;
      if (!tag || !matches(tag)) continue;
      const extras = collection as unknown as CollectionExtras;
      // Absent rather than zero means a Steam build that does not expose it.
      // Deleting on "I could not tell" is not a trade worth making.
      if (Array.isArray(extras.allApps) && extras.allApps.length === 0) empty.push(tag);
    }
  } catch (error) {
    console.error("[retroarch] findEmptyCollections failed", error);
  }
  return empty;
}

/** Delete collections by tag. Returns how many went. */
export async function deleteCollections(tags: string[]): Promise<number> {
  let deleted = 0;
  for (const tag of tags) {
    try {
      const collection = findCollection(tag);
      if (!collection) continue;
      const extras = collection as unknown as CollectionExtras;
      // Re-checked at the moment of deleting, not trusted from when the list
      // was built: a dialog can sit open for a while, and a collection that
      // gained a game in between must not be deleted for being empty earlier.
      if ((extras.allApps?.length ?? 1) !== 0) continue;
      if (typeof extras.Delete !== "function") continue;
      await extras.Delete();
      deleted += 1;
    } catch (error) {
      console.error(`[retroarch] could not delete collection "${tag}"`, error);
    }
  }
  return deleted;
}

/** Remove our games from collections they no longer belong to. */
export async function pruneStaleCollections(stale: StaleCollection[]): Promise<number> {
  let pruned = 0;
  for (const entry of stale) {
    if (await removeAppsFromCollection(entry.tag, entry.appIds)) {
      pruned += entry.appIds.length;
    }
  }
  return pruned;
}

/** True when Steam still has a shortcut for this appId. */
export function shortcutExists(appId: number): boolean {
  try {
    return Boolean(appStore()?.GetAppOverviewByAppID?.(appId));
  } catch (error) {
    console.error("[retroarch] could not look up app", appId, error);
    // Assume it exists rather than inviting the user to delete a live entry.
    return true;
  }
}

/**
 * Rename an existing shortcut.
 *
 * The same call is used when creating one, where it is known to work. Whether
 * Steam refreshes an already-visible library entry immediately is less certain,
 * so the caller should not treat a stale-looking name as a failure.
 */
export function renameShortcut(appId: number, name: string): boolean {
  const apps = steamClient()?.Apps;
  if (!apps?.SetShortcutName) return false;
  try {
    apps.SetShortcutName(appId, name);
    return true;
  } catch (error) {
    console.error("[deckyemu] could not rename shortcut", appId, error);
    return false;
  }
}

/**
 * Steam's GameID for a shortcut.
 *
 * Read from the app overview when possible, since that is what Steam itself
 * passes to RunGame. The fallback computes it the way Steam encodes a non-Steam
 * shortcut -- the appid in the high 32 bits with the shortcut type bits set --
 * for the case where the overview has not materialised yet.
 */
function shortcutGameId(appId: number): string {
  try {
    const fromStore = appStore()?.GetAppOverviewByAppID?.(appId)?.gameid;
    if (fromStore) return String(fromStore);
  } catch (error) {
    console.error("[deckyemu] could not read gameid for", appId, error);
  }
  return ((BigInt(appId) << 32n) | 0x0200000000000000n).toString();
}

/**
 * Launch a game through Steam, exactly as selecting it in the library would.
 *
 * Going through Steam rather than running the script ourselves means gamescope,
 * Steam Input and the overlay all behave as they do in normal play -- which is
 * the point of a test launch.
 */
export function launchApp(appId: number): boolean {
  const apps = steamClient()?.Apps;
  if (!apps?.RunGame) return false;
  try {
    apps.RunGame(shortcutGameId(appId), "", -1, 100);
    return true;
  } catch (error) {
    console.error("[deckyemu] could not launch app", appId, error);
    return false;
  }
}

/**
 * Keep a shortcut out of the library without deleting it.
 *
 * For the setup shortcut, which exists only because gamescope composites nothing
 * Steam did not launch. It has to be a real Steam entry to work at all, and
 * nobody wants it on their shelf next to their games.
 *
 * Steam models hidden as a collection rather than a flag, which is why this goes
 * through `collectionStore` rather than `SteamClient.Apps`. Returns whether it
 * took: a failure here is untidy rather than broken -- the shortcut still works,
 * it is just visible -- so the caller carries on either way.
 */
export function setAppHidden(appId: number, hidden: boolean): boolean {
  try {
    const store = collectionStore() as unknown as {
      SetAppsAsHidden?: (appIds: number[], hidden: boolean) => void;
    } | null;
    if (typeof store?.SetAppsAsHidden !== "function") return false;
    store.SetAppsAsHidden([appId], hidden);
    return true;
  } catch (error) {
    console.error("[deckyemu] could not hide app", appId, error);
    return false;
  }
}

/** Point an adopted game's shortcut at its rebuilt launcher script. */
export function repointShortcut(appId: number, exe: string): boolean {
  const apps = steamClient()?.Apps;
  if (!apps?.SetShortcutExe) return false;
  try {
    apps.SetShortcutExe(appId, exe);
    apps.SetShortcutStartDir?.(appId, exe.slice(0, Math.max(0, exe.lastIndexOf("/"))));
    return true;
  } catch (error) {
    console.error("[retroarch] could not repoint shortcut", appId, error);
    return false;
  }
}

export interface CollectionMove {
  app_id: number;
  title: string;
  from: string;
  to: string;
}

/**
 * Move already-added games between collections after a settings change.
 *
 * Additions happen before removals so a game is never briefly in no collection
 * at all, which would show up as a flicker in the library.
 */
export async function migrateCollections(
  moves: CollectionMove[],
): Promise<{ moved: number; assignments: Record<string, string> }> {
  const assignments: Record<string, string> = {};
  if (moves.length === 0) return { moved: 0, assignments };

  const byTarget = new Map<string, number[]>();
  const bySource = new Map<string, number[]>();
  // Appended in place. Rebuilding the array per move copies every id already
  // grouped under that name, which is quadratic in the size of a rename -- and a
  // rename is exactly the operation that touches the whole library at once.
  const group = (map: Map<string, number[]>, tag: string, appId: number) => {
    const existing = map.get(tag);
    if (existing) existing.push(appId);
    else map.set(tag, [appId]);
  };
  for (const move of moves) {
    if (move.to) group(byTarget, move.to, move.app_id);
    if (move.from) group(bySource, move.from, move.app_id);
  }

  let moved = 0;
  for (const [tag, appIds] of byTarget) {
    if (await addAppsToCollection(tag, appIds)) {
      for (const appId of appIds) {
        assignments[String(appId)] = tag;
        moved += 1;
      }
    }
  }

  for (const [tag, appIds] of bySource) {
    // Only pull a game out of its old collection once it is safely in the new
    // one, so a failure mid-way leaves it findable rather than orphaned.
    const settled = appIds.filter((appId) => assignments[String(appId)]);
    if (settled.length > 0) await removeAppsFromCollection(tag, settled);
  }

  return { moved, assignments };
}
