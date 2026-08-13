import { afterEach, describe, expect, it, vi } from "vitest";

import { deleteCollections, findEmptyCollections, findUnfiledGames } from "./steam";

/**
 * The two functions that delete a Steam collection.
 *
 * They read `window.collectionStore`, which is a Steam client global with no
 * types to import and a shape that differs between builds -- which is exactly
 * why they are worth testing: every branch here exists because some build
 * behaved differently, and none of it was checked by anything before.
 *
 * The fake below mirrors the parts steam.ts touches: `userCollections` (a Map
 * on some builds, an array on others), `GetCollectionIDByUserTag`,
 * `GetCollection`, and the undocumented `allApps` / `Delete` pair.
 */
interface FakeCollection {
  displayName: string;
  allApps?: unknown[];
  /** Membership, as `Set` here because all steam.ts asks of it is `has`. */
  apps?: { has: (appId: number) => boolean };
  Delete?: () => Promise<void>;
}

function install(collections: FakeCollection[], { asMap = true } = {}) {
  const byTag = new Map(collections.map((c) => [c.displayName, c]));
  (globalThis as any).collectionStore = {
    userCollections: asMap ? byTag : collections,
    GetCollectionIDByUserTag: (tag: string) => (byTag.has(tag) ? tag : null),
    GetCollection: (id: string) => byTag.get(id),
  };
  return byTag;
}

afterEach(() => {
  delete (globalThis as any).collectionStore;
  vi.restoreAllMocks();
});

describe("findEmptyCollections", () => {
  const ours = (name: string) => name.startsWith("DeckyEmu");

  it("finds ours that hold nothing", () => {
    install([
      { displayName: "DeckyEmu - SNES", allApps: [] },
      { displayName: "DeckyEmu - N64", allApps: [{}, {}] },
    ]);
    expect(findEmptyCollections(ours)).toEqual(["DeckyEmu - SNES"]);
  });

  it("leaves an empty collection that is not ours", () => {
    install([{ displayName: "Favourites", allApps: [] }]);
    expect(findEmptyCollections(ours)).toEqual([]);
  });

  // Absent is not the same as zero. A Steam build that does not expose the
  // count must read as "cannot tell", never as "nothing there" -- deleting on
  // a guess is the one outcome with no way back.
  it("treats an unreadable count as do-not-touch", () => {
    install([{ displayName: "DeckyEmu - SNES" }]);
    expect(findEmptyCollections(ours)).toEqual([]);
  });

  it("reads userCollections whether it is a Map or an array", () => {
    install([{ displayName: "DeckyEmu - SNES", allApps: [] }], { asMap: false });
    expect(findEmptyCollections(ours)).toEqual(["DeckyEmu - SNES"]);
  });

  it("answers nothing rather than throwing when Steam is not there", () => {
    delete (globalThis as any).collectionStore;
    expect(findEmptyCollections(ours)).toEqual([]);
  });
});

/**
 * The check the library audit makes to find games missing from their shelf.
 *
 * Worth its own tests because the registry cannot answer it: a game recorded as
 * filed can simply not be there, and the migration is blind to that case by
 * construction.
 */
describe("findUnfiledGames", () => {
  it("finds a game that is not in the collection it belongs to", () => {
    install([{ displayName: "DeckyEmu - SNES", apps: new Set([11]) }]);
    expect(findUnfiledGames({ "11": "DeckyEmu - SNES", "22": "DeckyEmu - SNES" })).toEqual([
      { tag: "DeckyEmu - SNES", appIds: [22] },
    ]);
  });

  it("says nothing when every game is where it belongs", () => {
    install([{ displayName: "DeckyEmu - SNES", apps: new Set([11, 22]) }]);
    expect(findUnfiledGames({ "11": "DeckyEmu - SNES", "22": "DeckyEmu - SNES" })).toEqual([]);
  });

  // The deleted-in-Steam case, and the reason this cannot be answered from the
  // registry: every record still says filed.
  it("treats a collection that no longer exists as holding none of them", () => {
    install([]);
    expect(findUnfiledGames({ "11": "DeckyEmu - SNES", "22": "DeckyEmu - SNES" })).toEqual([
      { tag: "DeckyEmu - SNES", appIds: [11, 22] },
    ]);
  });

  it("groups by collection, so each shelf is one call", () => {
    install([
      { displayName: "DeckyEmu - SNES", apps: new Set<number>() },
      { displayName: "DeckyEmu - N64", apps: new Set<number>() },
    ]);
    expect(
      findUnfiledGames({ "11": "DeckyEmu - SNES", "22": "DeckyEmu - N64", "33": "DeckyEmu - SNES" }),
    ).toEqual([
      { tag: "DeckyEmu - SNES", appIds: [11, 33] },
      { tag: "DeckyEmu - N64", appIds: [22] },
    ]);
  });

  // Same rule as findEmptyCollections: a build that will not say is "cannot
  // tell", not "not there". Otherwise every game reads as unfiled and the
  // finding never clears however many times it is acted on.
  it("treats unreadable membership as do-not-report", () => {
    install([{ displayName: "DeckyEmu - SNES" }]);
    expect(findUnfiledGames({ "11": "DeckyEmu - SNES" })).toEqual([]);
  });

  // Collections turned off means no game belongs anywhere, which the backend
  // reports as no targets at all.
  it("reports nothing when there are no targets", () => {
    install([{ displayName: "DeckyEmu - SNES", apps: new Set<number>() }]);
    expect(findUnfiledGames({})).toEqual([]);
  });

  it("answers nothing rather than throwing when Steam is not there", () => {
    delete (globalThis as any).collectionStore;
    expect(findUnfiledGames({ "11": "DeckyEmu - SNES" })).toEqual([]);
  });
});

describe("deleteCollections", () => {
  it("deletes one that is still empty", async () => {
    const remove = vi.fn().mockResolvedValue(undefined);
    install([{ displayName: "DeckyEmu - SNES", allApps: [], Delete: remove }]);
    expect(await deleteCollections(["DeckyEmu - SNES"])).toBe(1);
    expect(remove).toHaveBeenCalledOnce();
  });

  // The list is built when the dialog opens and acted on when a button is
  // pressed, which can be a while later. A collection that gained a game in
  // between must survive.
  it("refuses one that has gained a game since the list was built", async () => {
    const remove = vi.fn();
    install([{ displayName: "DeckyEmu - SNES", allApps: [{}], Delete: remove }]);
    expect(await deleteCollections(["DeckyEmu - SNES"])).toBe(0);
    expect(remove).not.toHaveBeenCalled();
  });

  it("skips one Steam no longer knows about", async () => {
    install([]);
    expect(await deleteCollections(["DeckyEmu - SNES"])).toBe(0);
  });

  it("skips a build that exposes no Delete", async () => {
    install([{ displayName: "DeckyEmu - SNES", allApps: [] }]);
    expect(await deleteCollections(["DeckyEmu - SNES"])).toBe(0);
  });

  // One failure must not abandon the rest: these are batched from the library
  // check, and a half-done sweep is what leaves somebody re-running it.
  it("carries on after one throws, and counts only what went", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    install([
      { displayName: "DeckyEmu - A", allApps: [], Delete: () => Promise.reject(new Error("no")) },
      { displayName: "DeckyEmu - B", allApps: [], Delete: () => Promise.resolve() },
    ]);
    expect(await deleteCollections(["DeckyEmu - A", "DeckyEmu - B"])).toBe(1);
  });
});
