import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The review's store: steps a file needs before it is a game, disc sets, and
 * undo. Run with no component anywhere, because the review is unmounted for
 * most of an emulator or package install -- the condition the panel's first
 * version of the emulator chain failed under on a device.
 */

type Handler = (...args: any[]) => void;
const listeners: Record<string, Handler[]> = {};
const emit = (name: string, ...args: unknown[]) => {
  for (const fn of [...(listeners[name] || [])]) fn(...args);
};

const probeRom = vi.fn();
const installEmulator = vi.fn(async (..._args: unknown[]) => ({ ok: true }));
const installPs4Package = vi.fn(async (..._args: unknown[]) => ({
  ok: true, title_id: "CUSA00001", title: "Harbor Dash",
}));
const addGameToSteam = vi.fn();
const forgetGames = vi.fn(async (ids: number[]) => ({ games: ids.map((app_id) => ({ app_id })) }));
const unfileRoms = vi.fn(async (..._args: unknown[]) => ({ ok: true, returned: [], kept: [] }));
const removeShortcut = vi.fn();

vi.mock("./logError", () => ({ logError: vi.fn() }));
vi.mock("./host", () => ({
  addEventListener: (name: string, fn: Handler) => {
    (listeners[name] ||= []).push(fn);
    return fn;
  },
  removeEventListener: (name: string, fn: Handler) => {
    listeners[name] = (listeners[name] || []).filter((item) => item !== fn);
  },
}));
vi.mock("./steam", () => ({
  removeShortcut: (...args: unknown[]) => removeShortcut(...args),
  repointShortcut: vi.fn(),
}));
vi.mock("./collections", () => ({ unfileGames: vi.fn(async () => undefined) }));
vi.mock("./addToSteam", () => ({ addGameToSteam: (...args: unknown[]) => addGameToSteam(...args) }));
vi.mock("./backend", () => ({
  clearStashedArt: vi.fn(async () => ({ ok: true })),
  forgetGames: (...args: [number[]]) => forgetGames(...args),
  getStatus: vi.fn(async () => ({ found: true })),
  installCore: vi.fn(),
  installEmulator: (...args: unknown[]) => installEmulator(...args),
  installPs3Package: vi.fn(),
  installPs4Package: (...args: unknown[]) => installPs4Package(...args),
  installVitaPackage: vi.fn(),
  joinDiscToGame: vi.fn(),
  listInstalledPs3Games: vi.fn(),
  listInstalledPs4Games: vi.fn(async () => ({
    games: [{ title_id: "CUSA00001", title: "Harbor Dash", eboot: "/games/CUSA00001/eboot.bin" }],
  })),
  listInstalledVitaGames: vi.fn(),
  missingFirmware: vi.fn(async () => ({ missing: [] })),
  probeRom: (...args: unknown[]) => probeRom(...args),
  ps3CoreId: vi.fn(),
  ps4CoreId: vi.fn(async () => ({ ok: true, core_id: "emu:shadps4" })),
  resolveGameStashed: vi.fn(async (path: string) => ({
    title: "Harbor Dash", system: "", matched_name: "", match_kind: "exact",
    title_source: "libretro", art: {}, art_source: "none", art_game_name: "",
    core_id: "", rom_path: path, art_key: "",
  })),
  suggestCoresForExtension: vi.fn(async () => []),
  takeStashedArt: vi.fn(async () => ({})),
  unfileRoms: (...args: unknown[]) => unfileRoms(...args),
  unpackTransferredFile: vi.fn(),
  vitaCoreId: vi.fn(),
}));

const store = await import("./batchImport");

/** A probe with the fields the review reads, and nothing found. */
function probe(extra: Record<string, unknown> = {}) {
  return {
    provisional_title: "Harbor Dash",
    suggested_core_id: "",
    matching_cores: [],
    all_cores: [],
    system_for_core: {},
    disc_set: [],
    match_extension: "",
    what: "",
    ...extra,
  };
}

const playlistCore = { id: "swan_libretro", extensions: ["chd", "m3u"], databases: ["Sony - PlayStation"] };
const discOnlyCore = { id: "plain_libretro", extensions: ["chd"], databases: ["Sony - PlayStation"] };

beforeEach(() => {
  store.closeBatch();
  vi.clearAllMocks();
  for (const key of Object.keys(listeners)) delete listeners[key];
});

describe("a package whose emulator is missing", () => {
  it("installs the emulator, then the package, then is the game", async () => {
    const waiting = { installed: false, title_id: "", emulator_ready: false,
      emulator_id: "shadps4", emulator_name: "shadPS4" };
    probeRom
      .mockResolvedValueOnce(probe({ ps4_package: waiting }))
      .mockResolvedValueOnce(probe({ ps4_package: { ...waiting, emulator_ready: true } }));
    await store.startBatch([{ path: "/inbox/game.pkg", name: "game.pkg" }]);
    expect(store.getBatch().rows[0].verdict.step).toBe("emulator");

    const running = store.runStep("/inbox/game.pkg");
    // The install reports its end by event, with nothing mounted to hear it.
    await vi.waitFor(() => expect(installEmulator).toHaveBeenCalledWith("shadps4"));
    emit("emulator_install_done", "shadps4", true, "");
    const paths = await running;

    expect(installPs4Package).toHaveBeenCalledWith("/inbox/game.pkg");
    expect(paths).toEqual(["/games/CUSA00001/eboot.bin"]);
    const row = store.getBatch().rows[0];
    expect(row.coreId).toBe("emu:shadps4");
    expect(row.verdict.step ?? "").toBe("");
    // shadPS4 starts the eboot; only Vita3K is given a title id.
    expect(row.titleId).toBe("");
  });

  it("stops at a failed emulator install and says why", async () => {
    probeRom.mockResolvedValue(probe({ ps4_package: { installed: false, title_id: "",
      emulator_ready: false, emulator_id: "shadps4", emulator_name: "shadPS4" } }));
    await store.startBatch([{ path: "/inbox/game.pkg", name: "game.pkg" }]);
    const running = store.runStep("/inbox/game.pkg");
    await vi.waitFor(() => expect(installEmulator).toHaveBeenCalled());
    emit("emulator_install_done", "shadps4", false, "No room");
    expect(await running).toEqual([]);
    expect(store.getBatch().rows[0].error).toBe("No room");
    expect(installPs4Package).not.toHaveBeenCalled();
  });
});

describe("a disc set sent without its playlist", () => {
  const discs = ["Harbor Dash (Disc 1).chd", "Harbor Dash (Disc 2).chd"];
  const files = discs.map((name) => ({ path: `/inbox/${name}`, name }));

  it("is one row, asked about rather than merged silently", async () => {
    probeRom.mockResolvedValue(probe({
      suggested_core_id: playlistCore.id, matching_cores: [playlistCore], all_cores: [playlistCore],
      disc_set: discs,
    }));
    await store.startBatch(files);
    const rows = store.getBatch().rows;
    expect(rows).toHaveLength(1);
    expect(rows[0].verdict).toMatchObject({ bucket: "check", reason: "2 discs as one game" });
  });

  it("goes in as one entry, or one per disc when asked", async () => {
    probeRom.mockResolvedValue(probe({
      suggested_core_id: playlistCore.id, matching_cores: [playlistCore], all_cores: [playlistCore],
      disc_set: discs,
    }));
    addGameToSteam.mockResolvedValue({ ok: true, appId: 7, title: "x", notes: [], romPath: "/roms/x" });
    await store.startBatch(files);
    store.setDiscMode(files[0].path, "each");
    await store.addBatch();
    expect(addGameToSteam).toHaveBeenCalledTimes(2);
    expect(addGameToSteam.mock.calls.map(([plan]) => plan.discs)).toEqual([[], []]);
    expect(store.getBatch().rows[0].added).toHaveLength(2);
  });

  it("goes in one entry per disc when the emulator cannot change disc", async () => {
    probeRom.mockResolvedValue(probe({
      suggested_core_id: discOnlyCore.id, matching_cores: [discOnlyCore], all_cores: [discOnlyCore],
      disc_set: discs,
    }));
    addGameToSteam.mockResolvedValue({ ok: true, appId: 8, title: "x", notes: [], romPath: "/roms/x" });
    await store.startBatch(files);
    expect(store.discsMustSplit(store.getBatch().rows[0])).toBe(true);
    await store.addBatch();
    expect(addGameToSteam).toHaveBeenCalledTimes(2);
  });
});

describe("a game that is not ready", () => {
  it("cannot be ticked, and Add leaves it out", async () => {
    probeRom.mockResolvedValue(probe({ vita_package: { installed: false, title_id: "", emulator_ready: true,
      emulator_id: "vita3k", emulator_name: "Vita3K", licence: false, licence_candidates: [] } }));
    await store.startBatch([{ path: "/inbox/game.pkg", name: "game.pkg" }]);
    const path = store.getBatch().rows[0].path;
    store.setIncluded(path, true);
    expect(store.getBatch().rows[0].include).toBe(false);
    store.setTitle(path, "Harbor Dash");
    expect(store.getBatch().rows[0].include).toBe(false);
    expect(store.chosenRows(store.getBatch().rows)).toEqual([]);
  });
});

describe("files that are not games", () => {
  it("go under Other files without being probed, and are never added", async () => {
    await store.startBatch([
      { path: "/inbox/x.ips", name: "x.ips", other: "patch" },
      { path: "/inbox/y.deckyemu.json", name: "y.deckyemu.json", other: "definition" },
    ]);
    expect(probeRom).not.toHaveBeenCalled();
    const rows = store.getBatch().rows;
    expect(rows.map((row) => row.verdict.bucket)).toEqual(["other", "other"]);
    expect(store.chosenRows(rows)).toEqual([]);
  });
});
