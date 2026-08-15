import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The five steps of putting a prepared game into Steam.
 *
 * Two panels ran these separately and had already drifted apart, so what is
 * checked here is the pair of things the drift produced: what happens to the
 * shortcut when a later step fails, and what gets written down about where the
 * game was filed.
 *
 * `./backend` is mocked because it imports `@decky/api`, which will not load
 * under Node. `./steam` is not -- the filing is the thing under test, so it runs
 * for real against the same fake Steam globals every other suite here uses.
 */

const registerGame = vi.fn(async (..._args: unknown[]) => ({}));
const createOrReuseShortcut = vi.fn(async (..._args: unknown[]) => ({
  appId: 77,
  reused: false,
}));

vi.mock("./backend", () => ({ registerGame: (...args: unknown[]) => registerGame(...args) }));
vi.mock("./reuseShortcut", () => ({
  createOrReuseShortcut: (...args: unknown[]) => createOrReuseShortcut(...args),
}));

const { addPreparedGame } = await import("./addGame");
const removeShortcut = vi.fn();

const PREPARED = {
  title: "A Game",
  exe: "/home/deck/.local/share/deckyemu/a-game.sh",
  start_dir: "/home/deck/.local/share/deckyemu",
  launch_options: "",
  launcher_path: "/home/deck/.local/share/deckyemu/a-game.sh",
  collection_name: "[DeckyEmu] SNES",
  rom_path: "/home/deck/deckyemu/roms/snes/a-game.sfc",
};

/** A Steam that will accept a collection, or one that has none and cannot make one. */
function installSteam({ collections = true }: { collections?: boolean } = {}) {
  const filed: Record<string, number[]> = {};
  const byTag = new Map<string, unknown>();

  const make = (tag: string) => {
    filed[tag] = [];
    const collection = {
      displayName: tag,
      apps: { has: (appId: number) => filed[tag].includes(appId) },
      allApps: filed[tag],
      AsDragDropCollection: () => ({
        AddApps: (overviews: { appid: number }[]) => {
          for (const overview of overviews) filed[tag].push(overview.appid);
        },
        RemoveApps: () => undefined,
      }),
      Save: async () => undefined,
    };
    byTag.set(tag, collection);
    return collection;
  };

  (globalThis as any).collectionStore = collections
    ? {
        userCollections: byTag,
        GetCollectionIDByUserTag: (tag: string) => (byTag.has(tag) ? tag : null),
        GetCollection: (id: string) => byTag.get(id),
        NewUnsavedCollection: (tag: string) => make(tag),
      }
    : // A build with no collection support at all: `getOrCreateCollection`
      // returns nothing and filing cannot happen. Not an error -- the game is
      // still added -- but it must not be recorded as filed.
      undefined;

  (globalThis as any).appStore = {
    GetAppOverviewByAppID: (appid: number) => ({ appid, display_name: `Game ${appid}` }),
  };
  (globalThis as any).SteamClient = { Apps: { RemoveShortcut: removeShortcut } };
  return filed;
}

beforeEach(() => {
  registerGame.mockClear();
  removeShortcut.mockClear();
  createOrReuseShortcut.mockClear();
  createOrReuseShortcut.mockResolvedValue({ appId: 77, reused: false });
  registerGame.mockResolvedValue({});
});

afterEach(() => {
  delete (globalThis as any).collectionStore;
  delete (globalThis as any).appStore;
  delete (globalThis as any).SteamClient;
});

/** The collection argument register_game was called with -- the eighth. */
const recordedCollection = () => registerGame.mock.calls[0]?.[7];

describe("addPreparedGame, what gets recorded", () => {
  it("records the collection the game actually went into", async () => {
    const filed = installSteam();

    const result = await addPreparedGame({ prepared: PREPARED, romPath: "", coreId: "snes9x" });

    expect(filed["[DeckyEmu] SNES"]).toEqual([77]);
    expect(result.collection).toBe("[DeckyEmu] SNES");
    expect(recordedCollection()).toBe("[DeckyEmu] SNES");
  });

  /*
   * The reason this file exists. The backend used to compute the name a second
   * time and record that, so a game that never reached its shelf was written
   * down as being on it -- and the two operations that read this field, a
   * rename and a removal, then both worked on a collection the game was not in.
   */
  it("records no collection when the filing did not take", async () => {
    installSteam({ collections: false });

    const result = await addPreparedGame({ prepared: PREPARED, romPath: "", coreId: "snes9x" });

    expect(result.collection).toBe("");
    expect(recordedCollection()).toBe("");
    // Still added: a shelf is not the game.
    expect(registerGame).toHaveBeenCalledTimes(1);
  });

  it("records no collection when there was none to file into", async () => {
    installSteam();

    const result = await addPreparedGame({
      prepared: { ...PREPARED, collection_name: "" },
      romPath: "",
      coreId: "snes9x",
    });

    expect(result.collection).toBe("");
    expect(recordedCollection()).toBe("");
  });

  it("registers the ROM where the backend filed it, not where it was picked", async () => {
    installSteam();

    await addPreparedGame({
      prepared: PREPARED,
      romPath: "/home/deck/deckyemu/transfer/a-game.sfc",
      coreId: "snes9x",
    });

    expect(registerGame.mock.calls[0][2]).toBe(PREPARED.rom_path);
  });

  it("falls back to the picked ROM when the backend did not move it", async () => {
    installSteam();

    await addPreparedGame({
      prepared: { ...PREPARED, rom_path: undefined },
      romPath: "/mnt/sd/roms/a-game.sfc",
      coreId: "snes9x",
    });

    expect(registerGame.mock.calls[0][2]).toBe("/mnt/sd/roms/a-game.sfc");
  });
});

describe("addPreparedGame, rolling back", () => {
  it("removes a shortcut it created when a later step throws", async () => {
    installSteam();
    registerGame.mockRejectedValueOnce(new Error("the backend went away"));

    await expect(
      addPreparedGame({ prepared: PREPARED, romPath: "", coreId: "snes9x" }),
    ).rejects.toThrow("the backend went away");

    expect(removeShortcut).toHaveBeenCalledWith(77);
  });

  /*
   * The half that was wrong in the panel this came from: it rolled back on the
   * appid it was holding without asking where that appid came from. Reusing is
   * the normal path for re-adding a game whose record was lost, so the failure
   * deleted a working Steam entry that existed before the add began.
   */
  it("leaves a shortcut it only took over", async () => {
    installSteam();
    createOrReuseShortcut.mockResolvedValue({ appId: 77, reused: true });
    registerGame.mockRejectedValueOnce(new Error("the backend went away"));

    await expect(
      addPreparedGame({ prepared: PREPARED, romPath: "", coreId: "snes9x" }),
    ).rejects.toThrow("the backend went away");

    expect(removeShortcut).not.toHaveBeenCalled();
  });
});
