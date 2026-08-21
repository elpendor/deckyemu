import { describe, expect, it, vi } from "vitest";

/**
 * An answer that arrives after the question stopped mattering.
 *
 * The lookup is fired and not awaited -- by the core row, the system row, the
 * artwork button -- so it can come back after the game has been added and the
 * draft cleared. It did: the artwork rows reappeared on a panel with no ROM
 * selected, for a game already in Steam, and the only way out was picking
 * another file. Landing after a *different* ROM was picked is the quieter half
 * of the same bug: the previous game's name and cover on this one.
 *
 * `./backend` is mocked because it imports `@decky/api`, which will not load
 * under Node -- and `@decky/api` itself now, because `addFlow` reaches it
 * directly for the toast and the emulator install events. `./romDraft` is not:
 * the draft is the thing under test.
 */

vi.mock("@decky/api", () => ({
  toaster: { toast: vi.fn() },
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
}));

let answer: (value: unknown) => void = () => undefined;
const resolveGame = vi.fn(
  (..._args: unknown[]) =>
    new Promise((resolve) => {
      answer = resolve;
    }),
);

vi.mock("./backend", () => ({
  resolveGame: (...args: unknown[]) => resolveGame(...args),
  probeRom: vi.fn(),
  setSettings: vi.fn(),
  suggestCoresForExtension: vi.fn(),
  listInstalledPs3Games: vi.fn(),
  listInstalledPs4Games: vi.fn(),
  listInstalledVitaGames: vi.fn(),
  ps3CoreId: "emu:rpcs3",
  ps4CoreId: "emu:shadps4",
  vitaCoreId: "emu:vita3k",
}));

const { lookupArtwork, selectRom } = await import("./addFlow");
const { getDraft, resetDraft, updateDraft } = await import("./romDraft");
const { probeRom, setSettings, suggestCoresForExtension } = await import("./backend");

const found = { title: "Katamari Damacy", art: {}, system: "", matched_name: "", match_kind: "exact" };

describe("a lookup that comes back late", () => {
  it("writes its answer while the same game is still being added", async () => {
    resetDraft();
    updateDraft({ romPath: "/roms/ps2/katamari.iso" });
    const pending = lookupArtwork("/roms/ps2/katamari.iso", "emu:pcsx2");
    answer(found);
    await pending;
    expect(getDraft().title).toBe("Katamari Damacy");
    expect(getDraft().resolved).not.toBeNull();
  });

  /*
   * The reported bug. Add clears the draft; the lookup answers a moment later
   * and used to put `resolved` and `title` back, leaving a panel showing
   * artwork rows for a game that was already in Steam.
   */
  it("says nothing once the game has been added and the draft cleared", async () => {
    resetDraft();
    updateDraft({ romPath: "/roms/ps2/katamari.iso" });
    const pending = lookupArtwork("/roms/ps2/katamari.iso", "emu:pcsx2");
    resetDraft();
    answer(found);
    await pending;
    expect(getDraft().resolved).toBeNull();
    expect(getDraft().title).toBe("");
    expect(getDraft().romPath).toBe("");
  });

  // The quieter half: one game's answer must never land on the next one.
  it("does not put the last game's name on the next one", async () => {
    resetDraft();
    updateDraft({ romPath: "/roms/ps2/katamari.iso" });
    const pending = lookupArtwork("/roms/ps2/katamari.iso", "emu:pcsx2");

    resetDraft();
    updateDraft({ romPath: "/roms/gc/luigi.iso", title: "Luigi's Mansion" });
    answer(found);
    await pending;

    expect(getDraft().title).toBe("Luigi's Mansion");
    expect(getDraft().resolved).toBeNull();
  });

  // A failure is a write too, and the same rule applies to it: the error row
  // belongs to the draft that asked, not to whatever is on screen now.
  it("keeps its failure to itself as well", async () => {
    resetDraft();
    updateDraft({ romPath: "/roms/ps2/katamari.iso" });
    const rejecting = Promise.reject(new Error("backend gone"));
    resolveGame.mockImplementationOnce(() => rejecting as never);
    const pending = lookupArtwork("/roms/ps2/katamari.iso", "emu:pcsx2");
    resetDraft();
    await pending;
    expect(getDraft().error).toBe("");
    expect(getDraft().looking).toBe(false);
  });
});

describe("picking another ROM while a package is unpacking", () => {
  it("takes the progress bar with the game it belonged to", async () => {
    // The bar says a *package* is being extracted, and the new selection is not
    // that package. Left standing it reports the previous file's install as
    // this one's, which is a progress bar for something that was never started.
    // The extraction itself carries on and reports its own end.
    vi.mocked(probeRom).mockResolvedValue({
      provisional_title: "Luigi's Mansion",
      matching_cores: [],
      match_extension: "iso",
      suggested_core_id: "",
    } as never);
    vi.mocked(setSettings).mockResolvedValue(undefined as never);
    vi.mocked(suggestCoresForExtension).mockResolvedValue([] as never);

    resetDraft();
    updateDraft({
      romPath: "/home/deck/deckyemu/transfer/game.pkg",
      unpacking: true,
      unpackPercent: 40,
      unpackStatus: "Unpacking",
    });

    await selectRom("/roms/gc/luigi.iso");

    expect(getDraft().unpacking).toBe(false);
    expect(getDraft().unpackPercent).toBe(0);
    expect(getDraft().unpackStatus).toBe("");
  });
});
