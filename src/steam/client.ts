/**
 * The Steam globals themselves, and the waiting that using them requires.
 *
 * `SteamClient`, `appStore` and `collectionStore` are injected by the client and
 * documented nowhere, so they are reached through these accessors rather than
 * imported, and the shapes below describe only the parts this plugin uses. A
 * Steam update that renames a method should degrade one feature, not break the
 * panel.
 *
 * Shared by the three modules beside this one. Not exported from the package:
 * nothing outside `steam/` should be reading a global directly.
 */
/** Matches ELibraryAssetType in decky-frontend-lib / generated Steam types. */
export const enum LibraryAssetType {
  Capsule = 0,
  Hero = 1,
  Logo = 2,
  Header = 3,
  Icon = 4,
  HeroBlur = 5,
}

export interface AppOverview {
  appid: number;
  display_name?: string;
  /** Steam's 64-bit GameID as a string. RunGame wants this, not the appid. */
  gameid?: string;
}

export interface Collection {
  AsDragDropCollection: () => {
    AddApps: (overviews: AppOverview[]) => void;
    RemoveApps: (overviews: AppOverview[]) => void;
  };
  Save: () => Promise<void>;
  apps: { has: (appId: number) => boolean };
  displayName: string;
}

export interface CollectionStore {
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

export interface CollectionExtras {
  Delete: () => Promise<void>;
  allApps: AppOverview[];
}

// `any` deliberately: these are undocumented globals the Steam client injects.
// There is nothing to import types from, and their shape changes between builds
// -- the interfaces above describe only the parts this file actually uses, which
// is why every call site checks for the method before calling it.

export const steamClient = (): any => (window as any).SteamClient;

export const appStore = (): any => (window as any).appStore;

export const collectionStore = (): CollectionStore | null =>
  (window as any).collectionStore ?? null;

export const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** A freshly added shortcut takes a moment to appear in appStore. */
export async function waitForOverview(appId: number, attempts = 12): Promise<AppOverview | null> {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const overview = appStore()?.GetAppOverviewByAppID?.(appId);
    if (overview) return overview as AppOverview;
    await sleep(250);
  }
  return null;
}

/**
 * Overviews for `appIds`, waiting for any that Steam has not registered yet.
 *
 * Waited for together rather than one after another. The wait is Steam's own
 * bookkeeping catching up, which it does for every app at once, so serialising it
 * charged a second per app that was not ready yet -- and a collection rename hands
 * this the entire library at once.
 */
export async function overviewsFor(appIds: number[]): Promise<AppOverview[]> {
  const settled = await Promise.all(appIds.map((appId) => waitForOverview(appId, 4)));

  const overviews: AppOverview[] = [];
  settled.forEach((overview, index) => {
    if (overview) overviews.push(overview);
    else console.warn(`[deckyemu] no app overview for ${appIds[index]}`);
  });
  return overviews;
}
