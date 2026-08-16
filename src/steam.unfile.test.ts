import { afterEach, describe, expect, it, vi } from "vitest";

import { findFiledGames, migrateCollections } from "./steam";

/**
 * Taking games out of collections without putting them anywhere.
 *
 * This is the move the migration could not express: every plan was A to B, so
 * switching collections off produced no moves and the shelves stayed exactly as
 * they were. The interesting part is not the removal, it is what happens to the
 * collection afterwards -- ours may be holding games the user dragged in, and
 * deleting one of those would destroy something the plugin did not create.
 */
interface FakeCollection {
  displayName: string;
  allApps: unknown[];
  removed: number[];
  deleted: boolean;
}

function install(collections: Record<string, number[]>, extras: Record<string, number> = {}) {
  const state: Record<string, FakeCollection> = {};
  const byTag = new Map<string, unknown>();

  for (const [tag, appIds] of Object.entries(collections)) {
    const foreign = extras[tag] ?? 0;
    const record: FakeCollection = {
      displayName: tag,
      // Ours plus however many the user put there themselves.
      allApps: [...appIds, ...Array.from({ length: foreign }, () => ({}))],
      removed: [],
      deleted: false,
    };
    state[tag] = record;

    byTag.set(tag, {
      displayName: tag,
      apps: { has: (appId: number) => appIds.includes(appId) },
      allApps: record.allApps,
      AsDragDropCollection: () => ({
        AddApps: () => undefined,
        RemoveApps: (overviews: { appid: number }[]) => {
          for (const overview of overviews) {
            record.removed.push(overview.appid);
            const at = record.allApps.indexOf(overview.appid as unknown);
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
  (globalThis as any).appStore = {
    GetAppOverviewByAppID: (appid: number) => ({ appid, display_name: `Game ${appid}` }),
  };
  return state;
}

afterEach(() => {
  delete (globalThis as any).collectionStore;
  delete (globalThis as any).appStore;
  vi.restoreAllMocks();
});

const unfile = (appId: number, from: string) => ({
  app_id: appId,
  title: `Game ${appId}`,
  from,
  to: "",
});

describe("migrateCollections, unfiling", () => {
  it("takes the games out and deletes the collection it emptied", async () => {
    const state = install({ "[DeckyEmu] SNES": [11, 12] });

    const { moved, assignments } = await migrateCollections([
      unfile(11, "[DeckyEmu] SNES"),
      unfile(12, "[DeckyEmu] SNES"),
    ]);

    expect(state["[DeckyEmu] SNES"].removed.sort()).toEqual([11, 12]);
    expect(state["[DeckyEmu] SNES"].deleted).toBe(true);
    expect(moved).toBe(2);
    // Recorded as belonging nowhere, so the entry stops naming a collection
    // that no longer exists.
    expect(assignments).toEqual({ "11": "", "12": "" });
  });

  it("keeps a collection that still holds games the user put there", async () => {
    const state = install({ "[DeckyEmu] N64": [21] }, { "[DeckyEmu] N64": 2 });

    await migrateCollections([unfile(21, "[DeckyEmu] N64")]);

    expect(state["[DeckyEmu] N64"].removed).toEqual([21]);
    expect(state["[DeckyEmu] N64"].deleted).toBe(false);
  });

  it("unfiles across several collections at once", async () => {
    const state = install({ "[DeckyEmu] SNES": [31], "[DeckyEmu] PS1": [32] });

    const { moved } = await migrateCollections([
      unfile(31, "[DeckyEmu] SNES"),
      unfile(32, "[DeckyEmu] PS1"),
    ]);

    expect(moved).toBe(2);
    expect(state["[DeckyEmu] SNES"].deleted).toBe(true);
    expect(state["[DeckyEmu] PS1"].deleted).toBe(true);
  });

  it("still moves games between collections, which is the other half", async () => {
    const state = install({ "Old": [41], "New": [] });

    const { moved, assignments } = await migrateCollections([
      { app_id: 41, title: "Game 41", from: "Old", to: "New" },
    ]);

    expect(moved).toBe(1);
    expect(assignments).toEqual({ "41": "New" });
    expect(state["Old"].removed).toEqual([41]);
  });

  it("records nothing when the removal fails, so a repair can retry", async () => {
    install({ "[DeckyEmu] SNES": [51] });
    // The collection vanishes between the plan and the move.
    (globalThis as any).collectionStore.GetCollection = () => {
      throw new Error("gone");
    };

    const { moved, assignments } = await migrateCollections([unfile(51, "[DeckyEmu] SNES")]);

    expect(moved).toBe(0);
    expect(assignments).toEqual({});
  });
});

describe("findFiledGames", () => {
  const ours = (name: string) => name.startsWith("[DeckyEmu]");

  /**
   * The failure this exists for: a game sitting in a collection whose entry
   * records no collection at all -- added by a build that did not store it, or
   * left behind by an unfiling that failed after clearing the record. Asking
   * the registry returns nothing, so "turn collections off" did nothing while
   * the shelves stayed on screen. Steam is the one that knows.
   */
  it("finds a collection holding a game the registry forgot", () => {
    install({ "[DeckyEmu] SNES": [61] });

    expect(findFiledGames([61], ours)).toEqual([{ tag: "[DeckyEmu] SNES", appIds: [61] }]);
  });

  /**
   * This asserted the opposite -- that "Favourites" was reported alongside ours
   * -- and turning collections off duly emptied it. Reporting every collection
   * a game is in is the same question as which are ours to empty only when the
   * user keeps our games nowhere else, and they do: a shelf of their own, or
   * another plugin's, holding a game we added is ordinary.
   */
  it("reports only collections this plugin made, not every one a game is in", () => {
    install({ "[DeckyEmu] SNES": [62], "Favourites": [62] });

    const found = findFiledGames([62], ours);
    expect(found.map((group) => group.tag)).toEqual(["[DeckyEmu] SNES"]);
  });

  it("ignores collections holding nothing of ours", () => {
    install({ "Someone else's shelf": [99] });

    expect(findFiledGames([63], ours)).toEqual([]);
  });

  it("is empty when no games are registered", () => {
    install({ "[DeckyEmu] SNES": [64] });

    expect(findFiledGames([], ours)).toEqual([]);
  });
});
