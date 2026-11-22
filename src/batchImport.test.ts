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
const missingFirmware = vi.fn(async (..._args: unknown[]) => ({ missing: [] as unknown[] }));

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
  missingFirmware: (...args: unknown[]) => missingFirmware(...args),
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

  it("is one row, ready as one game", async () => {
    probeRom.mockResolvedValue(probe({
      suggested_core_id: playlistCore.id, matching_cores: [playlistCore], all_cores: [playlistCore],
      disc_set: discs,
    }));
    await store.startBatch(files);
    const rows = store.getBatch().rows;
    expect(rows).toHaveLength(1);
    expect(rows[0].verdict.bucket).toBe("ready");
    expect(rows[0].discs).toEqual(discs);
    expect(rows[0].discMode).toBe("one");
  });

  it("goes in as one entry, or one per disc when asked", async () => {
    probeRom.mockResolvedValue(probe({
      suggested_core_id: playlistCore.id, matching_cores: [playlistCore], all_cores: [playlistCore],
      disc_set: discs,
    }));
    addGameToSteam.mockResolvedValue({ ok: true, appId: 7, title: "x", notes: [], romPath: "/roms/x", contentInstalled: [] });
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
    addGameToSteam.mockResolvedValue({ ok: true, appId: 8, title: "x", notes: [], romPath: "/roms/x", contentInstalled: [] });
    await store.startBatch(files);
    expect(store.discsMustSplit(store.getBatch().rows[0])).toBe(true);
    await store.addBatch();
    expect(addGameToSteam).toHaveBeenCalledTimes(2);
  });
});

describe("a disc set, this disc only", () => {
  const discs = ["Harbor Dash (Disc 1).chd", "Harbor Dash (Disc 2).chd"];
  const files = discs.map((name) => ({ path: "/inbox/" + name, name }));

  it("adds the row's own disc alone, with no playlist", async () => {
    probeRom.mockResolvedValue(probe({
      suggested_core_id: discOnlyCore.id, matching_cores: [discOnlyCore], all_cores: [discOnlyCore],
      disc_set: discs,
    }));
    addGameToSteam.mockResolvedValue({ ok: true, appId: 3, title: "x", notes: [], romPath: "/roms/x", contentInstalled: [] });
    await store.startBatch(files);
    store.setDiscMode(files[0].path, "single");
    expect(store.discPlan(store.getBatch().rows[0])).toBe("single");
    await store.addBatch();
    expect(addGameToSteam).toHaveBeenCalledTimes(1);
    expect(addGameToSteam.mock.calls[0][0]).toMatchObject({ romPath: files[0].path, discs: [] });
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

describe("a BIOS set kept one per region", () => {
  const needs = {
    emulator: "X", download: [],
    send: [
      { name: "jp.bin", label: "PS1 JP BIOS" },
      { name: "us.bin", label: "PS1 US BIOS" },
      { name: "eu.bin", label: "PS1 EU BIOS" },
    ],
  };

  it("asks only for the game's own region", () => {
    expect(store.sendFor({ name: "Harbor Dash (USA) (Disc 1).cue", needs })).toEqual(["us.bin"]);
    expect(store.sendFor({ name: "Harbor Dash (Europe).chd", needs })).toEqual(["eu.bin"]);
    expect(store.sendFor({ name: "Harbor Dash (Japan).chd", needs })).toEqual(["jp.bin"]);
  });

  it("asks for all of them when the game's region is not said", () => {
    expect(store.sendFor({ name: "Harbor Dash.chd", needs })).toHaveLength(3);
  });
});

describe("updates and DLC sent with their game", () => {
  it("are counted on the game's row and go in with it", async () => {
    probeRom.mockResolvedValue(probe({
      suggested_core_id: playlistCore.id, matching_cores: [playlistCore], all_cores: [playlistCore],
      content_waiting: [
        { path: "/inbox/u.nsp", name: "u.nsp", label: "Update v2" },
        { path: "/inbox/d.nsp", name: "d.nsp", label: "DLC" },
      ],
    }));
    await store.startBatch([{ path: "/inbox/game.nsp", name: "game.nsp" }]);
    const row = store.getBatch().rows[0];
    expect(store.contentSummary(row)).toBe("+ 1 update · 1 DLC");
    expect(store.contentWithGames(store.getBatch().rows).get("d.nsp")).toBe(row.title);
  });
});

describe("an emulator missing what no game starts without", () => {
  it("warns on the game, which can still be added", async () => {
    probeRom.mockResolvedValue(probe({
      suggested_core_id: "emu:switchy", matching_cores: [playlistCore], all_cores: [playlistCore],
    }));
    missingFirmware.mockResolvedValueOnce({ missing: [
      { name: "keys.bin", blocks: true, waiting: false },
      { name: "firmware.zip", waiting: false },
    ] });
    await store.startBatch([{ path: "/inbox/game.nsp", name: "game.nsp" }]);
    const row = store.getBatch().rows[0];
    // Found by name only, so one kept under another name reads as missing.
    expect(row.verdict).toMatchObject({ bucket: "check", include: true });
    expect(row.verdict.blocked ?? false).toBe(false);
    expect(row.verdict.reason).toContain("keys.bin");
    expect(row.verdict.reason).not.toContain("firmware.zip");
    expect(store.chosenRows(store.getBatch().rows)).toHaveLength(1);
  });

  it("stops warning when the review reopens, once the file is sent", async () => {
    probeRom.mockResolvedValue(probe({
      suggested_core_id: "emu:later", matching_cores: [playlistCore], all_cores: [playlistCore],
    }));
    missingFirmware.mockResolvedValueOnce({ missing: [{ name: "keys.bin", blocks: true, waiting: false }] });
    const files = [{ path: "/inbox/game.nsp", name: "game.nsp" }];
    await store.startBatch(files);
    expect(store.getBatch().rows[0].verdict.reason).toContain("keys.bin");
    // Sent meanwhile: the emulator now reports nothing missing.
    store.resumeOrStartBatch(files);
    await vi.waitFor(() => expect(store.getBatch().rows[0].verdict.reason).not.toContain("keys.bin"));
    expect(store.getBatch().rows[0].include).toBe(true);
  });

  it("warns only for the file types that need it", async () => {
    probeRom.mockResolvedValue(probe({
      suggested_core_id: "emu:discy", matching_cores: [playlistCore], all_cores: [playlistCore],
    }));
    missingFirmware.mockResolvedValue({ missing: [{ name: "keys.txt", blocks: ["wud"], waiting: false }] });
    await store.startBatch([
      { path: "/inbox/a.wud", name: "a.wud" },
      { path: "/inbox/b.wua", name: "b.wua" },
    ]);
    const [disc, archive] = store.getBatch().rows;
    expect(disc.verdict.reason).toContain("keys.txt");
    expect(archive.verdict.reason).not.toContain("keys.txt");
    expect(store.sendFor(archive)).toEqual(["keys.txt"]);
  });
});

describe("a file nothing claims", () => {
  const other = { id: "emu:custom", extensions: ["zzz"], databases: ["Custom"] };

  it("waits for an emulator picked by hand, then is added with it", async () => {
    probeRom.mockResolvedValue(probe({ what: ".xyz", all_cores: [other] }));
    addGameToSteam.mockResolvedValue({ ok: true, appId: 9, title: "x", notes: [], romPath: "/roms/x", contentInstalled: [] });
    const path = "/inbox/game.xyz";
    await store.startBatch([{ path, name: "game.xyz" }]);
    expect(store.getBatch().rows[0].verdict).toMatchObject({ bucket: "check", blocked: true, pick: true });
    expect(store.chosenRows(store.getBatch().rows)).toEqual([]);

    await store.setRowCore(path, other.id);
    await vi.waitFor(() => expect(store.getBatch().rows[0].busy).toBe(false));
    const row = store.getBatch().rows[0];
    expect(row.verdict.blocked ?? false).toBe(false);
    expect(row.include).toBe(true);
    await store.addBatch();
    expect(addGameToSteam.mock.calls[0][0]).toMatchObject({ coreId: other.id, romPath: path });
  });

  it("keeps the pick when the review reopens", async () => {
    probeRom.mockResolvedValue(probe({ what: ".xyz", all_cores: [other] }));
    const files = [{ path: "/inbox/game.xyz", name: "game.xyz" }];
    await store.startBatch(files);
    await store.setRowCore(files[0].path, other.id);
    await vi.waitFor(() => expect(store.getBatch().rows[0].busy).toBe(false));
    store.resumeOrStartBatch(files);
    await vi.waitFor(() => expect(probeRom).toHaveBeenCalledTimes(2));
    await vi.waitFor(() => expect(store.getBatch().rows[0].busy).toBe(false));
    const row = store.getBatch().rows[0];
    expect(row.coreId).toBe(other.id);
    expect(row.verdict.blocked ?? false).toBe(false);
    // Found on the Deck: the pick came back, unticked.
    expect(row.include).toBe(true);
  });
});

describe("what adding a game reports", () => {
  it("keeps the notes past the artwork, and marks done only content that went in", async () => {
    probeRom.mockResolvedValue(probe({
      suggested_core_id: playlistCore.id, matching_cores: [playlistCore], all_cores: [playlistCore],
      content_waiting: [
        { path: "/inbox/u.nsp", name: "u.nsp", label: "Update v2" },
        { path: "/inbox/d.nsp", name: "d.nsp", label: "DLC" },
      ],
    }));
    addGameToSteam.mockResolvedValue({
      ok: true, appId: 5, title: "x", romPath: "/roms/x",
      notes: ["no artwork found", "could not add it to its collection"],
      contentInstalled: ["u.nsp"],
    });
    await store.startBatch([
      { path: "/inbox/game.nsp", name: "game.nsp" },
      { path: "/inbox/u.nsp", name: "u.nsp", other: "content" },
      { path: "/inbox/d.nsp", name: "d.nsp", other: "content" },
    ]);
    await store.addBatch();
    const [game, update, dlc] = store.getBatch().rows;
    expect(game.notes).toEqual(["could not add it to its collection"]);
    expect(update.outcome).toBe("done");
    expect(dlc.outcome).toBe("");
  });
});

describe("reopening the review", () => {
  const files = [{ path: "/inbox/game.chd", name: "game.chd" }];
  const runnable = probe({
    suggested_core_id: playlistCore.id, matching_cores: [playlistCore], all_cores: [playlistCore],
  });

  it("notices an emulator removed meanwhile", async () => {
    probeRom.mockResolvedValue(runnable);
    await store.startBatch(files);
    expect(store.getBatch().rows[0].include).toBe(true);
    probeRom.mockResolvedValue(probe({ what: ".chd" }));
    store.resumeOrStartBatch(files);
    await vi.waitFor(() => expect(store.getBatch().rows[0].verdict.bucket).toBe("cant"));
    expect(store.chosenRows(store.getBatch().rows)).toEqual([]);
  });

  it("keeps a name typed and a game unticked", async () => {
    probeRom.mockResolvedValue(runnable);
    await store.startBatch(files);
    const path = store.getBatch().rows[0].path;
    store.setTitle(path, "Harbor Dash Deluxe");
    store.setIncluded(path, false);
    store.resumeOrStartBatch(files);
    await vi.waitFor(() => expect(probeRom).toHaveBeenCalledTimes(2));
    await vi.waitFor(() => expect(store.getBatch().rows[0].busy).toBe(false));
    const row = store.getBatch().rows[0];
    expect(row.title).toBe("Harbor Dash Deluxe");
    expect(row.include).toBe(false);
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
