import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Taking games off their shelves.
 *
 * Four places did this with their own copy of the same loop, and they had
 * drifted: three took the games out of their collections before removing the
 * Steam shortcuts and one did it the other way round, which does not work at
 * all. That asymmetry is what these checks are really about -- the grouping is
 * the easy half.
 *
 * `./backend` is mocked because it imports `@decky/api`, which will not load
 * under Node. `./steam` runs for real against the same fake Steam globals the
 * rest of the suite uses, since the whole question is what Steam is asked to do.
 */

const collectionShape = vi.fn(async () => ({
  base: "DeckyEmu",
  per_platform: true,
  template: "[{name}] {platform}",
  known: [] as string[],
}));
const forgetCollections = vi.fn(async (..._args: unknown[]) => ({
  ok: true,
  forgotten: [] as string[],
}));

vi.mock("./backend", () => ({
  collectionShape: () => collectionShape(),
  forgetCollections: (...args: unknown[]) => forgetCollections(...args),
}));

const { sweepEmptyCollections, unfileGames } = await import("./collections");

interface Fake {
  displayName: string;
  allApps: unknown[];
  removed: number[];
  deleted: boolean;
}

/** Steam with `collections` present, and `live` the apps that still resolve. */
function installSteam(collections: Record<string, number[]>, live?: number[]) {
  const state: Record<string, Fake> = {};
  const byTag = new Map<string, unknown>();

  for (const [tag, appIds] of Object.entries(collections)) {
    const record: Fake = {
      displayName: tag,
      allApps: [...appIds],
      removed: [],
      deleted: false,
    };
    state[tag] = record;
    byTag.set(tag, {
      displayName: tag,
      apps: { has: (appId: number) => record.allApps.includes(appId) },
      get allApps() {
        return record.allApps;
      },
      AsDragDropCollection: () => ({
        AddApps: () => undefined,
        RemoveApps: (overviews: { appid: number }[]) => {
          for (const overview of overviews) {
            record.removed.push(overview.appid);
            const at = record.allApps.indexOf(overview.appid);
            if (at >= 0) record.allApps.splice(at, 1);
          }
        },
      }),
      Save: async () => undefined,
      Delete: async () => {
        record.deleted = true;
      },
    });
  }

  (globalThis as any).collectionStore = {
    userCollections: byTag,
    GetCollectionIDByUserTag: (tag: string) => (byTag.has(tag) ? tag : null),
    GetCollection: (id: string) => byTag.get(id),
  };
  // An app that has been removed from Steam no longer has an overview. That is
  // the whole of the ordering problem, so it has to be expressible here.
  (globalThis as any).appStore = {
    GetAppOverviewByAppID: (appid: number) =>
      !live || live.includes(appid) ? { appid, display_name: `Game ${appid}` } : undefined,
  };
  return state;
}

beforeEach(() => {
  vi.useFakeTimers();
  forgetCollections.mockClear();
});

afterEach(() => {
  vi.useRealTimers();
  delete (globalThis as any).collectionStore;
  delete (globalThis as any).appStore;
});

/** Runs a promise that awaits Steam's retry sleeps without waiting for real. */
async function settle<T>(work: Promise<T>): Promise<T> {
  await vi.runAllTimersAsync();
  return work;
}

describe("unfileGames", () => {
  it("takes each game out of the collection it was filed into", async () => {
    const state = installSteam({ "[DeckyEmu] SNES": [1, 2], "[DeckyEmu] N64": [3] });

    const touched = await settle(
      unfileGames([
        { app_id: 1, collection: "[DeckyEmu] SNES" },
        { app_id: 3, collection: "[DeckyEmu] N64" },
      ]),
    );

    expect(touched).toBe(2);
    expect(state["[DeckyEmu] SNES"].removed).toEqual([1]);
    expect(state["[DeckyEmu] N64"].removed).toEqual([3]);
  });

  it("groups by collection, so a shelf is one call however many games leave it", async () => {
    const state = installSteam({ "[DeckyEmu] SNES": [1, 2, 3] });

    const touched = await settle(
      unfileGames([
        { app_id: 1, collection: "[DeckyEmu] SNES" },
        { app_id: 2, collection: "[DeckyEmu] SNES" },
        { app_id: 3, collection: "[DeckyEmu] SNES" },
      ]),
    );

    expect(touched).toBe(1);
    expect(state["[DeckyEmu] SNES"].removed).toEqual([1, 2, 3]);
  });

  it("deletes a collection it emptied", async () => {
    const state = installSteam({ "[DeckyEmu] SNES": [1] });
    await settle(unfileGames([{ app_id: 1, collection: "[DeckyEmu] SNES" }]));
    expect(state["[DeckyEmu] SNES"].deleted).toBe(true);
  });

  it("keeps one that still holds games somebody put there by hand", async () => {
    const state = installSteam({ "[DeckyEmu] SNES": [1, 999] });
    await settle(unfileGames([{ app_id: 1, collection: "[DeckyEmu] SNES" }]));
    expect(state["[DeckyEmu] SNES"].deleted).toBe(false);
  });

  /*
   * The reason this module exists. Steam removes an app from a collection by
   * its overview, and an overview stops existing with the shortcut -- so a
   * caller that removed the shortcut first got a silent no-op, a collection
   * still listing an id that resolves to nothing, and a shelf that could never
   * read as empty again. One of the four callers did exactly that.
   */
  it("cannot unfile a game whose shortcut is already gone", async () => {
    const state = installSteam({ "[DeckyEmu] SNES": [1] }, []);
    await settle(unfileGames([{ app_id: 1, collection: "[DeckyEmu] SNES" }]));
    expect(state["[DeckyEmu] SNES"].removed).toEqual([]);
    expect(state["[DeckyEmu] SNES"].deleted).toBe(false);
  });

  it("skips a game that was never filed anywhere", async () => {
    const state = installSteam({ "[DeckyEmu] SNES": [1] });
    const touched = await settle(
      unfileGames([{ app_id: 1, collection: "" }, { app_id: 2 }]),
    );
    expect(touched).toBe(0);
    expect(state["[DeckyEmu] SNES"].removed).toEqual([]);
  });

  it("reports progress per collection, for the callers clearing a whole library", async () => {
    installSteam({ a: [1], b: [2], c: [3] });
    const seen: Array<[number, number]> = [];

    await settle(
      unfileGames(
        [
          { app_id: 1, collection: "a" },
          { app_id: 2, collection: "b" },
          { app_id: 3, collection: "c" },
        ],
        (done, total) => seen.push([done, total]),
      ),
    );

    expect(seen).toEqual([
      [0, 3],
      [1, 3],
      [2, 3],
    ]);
  });
});

/*
 * Ownership is recorded now, not derived from the naming -- so a collection
 * that is deleted has to be given back, or the plugin goes on claiming a shelf
 * that no longer exists and would claim a new one if the user ever made a
 * collection of their own by that name. That is the one way recording ownership
 * could be worse than deriving it, so every path that deletes is checked for it.
 */
describe("deleting a collection stops it being claimed", () => {
  it("when unfiling emptied it", async () => {
    installSteam({ "[DeckyEmu] SNES": [1] });
    await settle(unfileGames([{ app_id: 1, collection: "[DeckyEmu] SNES" }]));
    expect(forgetCollections).toHaveBeenCalledWith(["[DeckyEmu] SNES"]);
  });

  it("but not when the collection survived", async () => {
    installSteam({ "[DeckyEmu] SNES": [1, 999] });
    await settle(unfileGames([{ app_id: 1, collection: "[DeckyEmu] SNES" }]));
    expect(forgetCollections).not.toHaveBeenCalled();
  });

  it("and a failure to unclaim does not fail the removal", async () => {
    const state = installSteam({ "[DeckyEmu] SNES": [1] });
    forgetCollections.mockRejectedValueOnce(new Error("the backend went away"));

    await expect(
      settle(unfileGames([{ app_id: 1, collection: "[DeckyEmu] SNES" }])),
    ).resolves.toBe(1);
    // The shelf is still gone from Steam, which is what the user asked for. A
    // name left claimed costs nothing until such a collection exists again.
    expect(state["[DeckyEmu] SNES"].deleted).toBe(true);
  });
});

describe("sweepEmptyCollections", () => {
  it("deletes ours that hold nothing and leaves everything else", async () => {
    const state = installSteam({
      "[DeckyEmu] SNES": [],
      "[DeckyEmu] N64": [7],
      "Shooters I like": [],
    });

    const deleted = await settle(sweepEmptyCollections());

    expect(deleted).toBe(1);
    expect(state["[DeckyEmu] SNES"].deleted).toBe(true);
    expect(forgetCollections).toHaveBeenCalledWith(["[DeckyEmu] SNES"]);
    // Still holds a game.
    expect(state["[DeckyEmu] N64"].deleted).toBe(false);
    // Empty, but not one of ours -- somebody's own shelf is theirs to keep.
    expect(state["Shooters I like"].deleted).toBe(false);
  });
});
