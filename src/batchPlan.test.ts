import { describe, expect, it } from "vitest";

import type { ResolvedGame, RomProbe } from "./backend";
import { classify, classifyProbe } from "./batchPlan";

/**
 * Where each file lands on the batch review. What starts ticked is what gets
 * added if nobody looks, so the defaults are the part worth pinning.
 */

function probe(extra: Partial<RomProbe> = {}): RomProbe {
  return {
    extension: "sfc",
    match_extension: "sfc",
    what: ".sfc",
    can_unpack: false,
    unpack_kind: "zip",
    archived_content: "",
    save_backup: null,
    already_added: null,
    disc_set: [],
    disc_playlist: "",
    disc_folder_warning: "",
    track_warning: "",
    is_archive: false,
    provisional_title: "Harbor Dash",
    matching_cores: [],
    all_cores: [],
    suggested_core_id: "snes9x_libretro",
    unsupported_extension: false,
    system_for_core: {},
    ...extra,
  } as RomProbe;
}

function resolved(extra: Partial<ResolvedGame> = {}): ResolvedGame {
  return {
    title: "Harbor Dash",
    system: "Nintendo - Super Nintendo Entertainment System",
    matched_name: "Harbor Dash (USA)",
    match_kind: "exact",
    title_source: "libretro",
    art: {},
    art_source: "libretro",
    art_game_name: "",
    core_id: "snes9x_libretro",
    rom_path: "/inbox/Harbor Dash.sfc",
    ...extra,
  } as ResolvedGame;
}

describe("classifyProbe", () => {
  it("leaves an ordinary ROM to the lookup", () => {
    expect(classifyProbe(probe())).toBeNull();
  });

  it("puts what belongs to a game under Other files, never ticked", () => {
    for (const [extra, kind] of [
      [{ save_backup: [] }, "save"],
      [{ rom_patch: { kind: "ips" } }, "patch"],
      [{ game_content: { label: "Update 1.1", app_id: 0, title: "" } }, "content"],
    ] as [Partial<RomProbe>, string][]) {
      expect(classifyProbe(probe(extra))).toMatchObject({ bucket: "other", other: kind, include: false });
    }
  });

  it("gives a package the step it needs, the emulator first", () => {
    const pkg = { installed: false, title_id: "", emulator_ready: true, emulator_id: "x", emulator_name: "X" };
    expect(classifyProbe(probe({ ps4_package: pkg } as Partial<RomProbe>)))
      .toMatchObject({ bucket: "check", step: "package", include: true });
    expect(classifyProbe(probe({ ps4_package: { ...pkg, emulator_ready: false } } as Partial<RomProbe>)))
      .toMatchObject({ step: "emulator", reason: "Installs X, then the game" });
  });

  it("waits for a person to pick a Vita key that is not named for the game", () => {
    const pkg = { installed: false, title_id: "", emulator_ready: true, emulator_id: "x",
      emulator_name: "X", licence: false, licence_candidates: ["other.zrif"] };
    expect(classifyProbe(probe({ vita_package: pkg } as Partial<RomProbe>)))
      .toMatchObject({ step: "package", include: false, reason: "Pick its licence key" });
  });

  it("unpacks what nothing can open as it is", () => {
    expect(classifyProbe(probe({ can_unpack: true, archived_content: "stfs", suggested_core_id: "" })))
      .toMatchObject({ step: "unpack", include: true });
  });

  it("offers a core, or RetroArch first, when one could run the file", () => {
    expect(classifyProbe(probe({ suggested_core_id: "" }), 2, true))
      .toMatchObject({ step: "core", include: true });
    expect(classifyProbe(probe({ suggested_core_id: "" }), 2, false))
      .toMatchObject({ step: "retroarch", include: false });
  });

  it("says which files nothing runs at all", () => {
    expect(classifyProbe(probe({ suggested_core_id: "", what: ".n64" }))?.reason).toBe(
      "Nothing runs .n64 files",
    );
    expect(classifyProbe(probe({ suggested_core_id: "", unsupported_extension: true }))?.bucket).toBe("cant");
  });
});

describe("classify", () => {
  it("puts an exact match in Ready, ticked", () => {
    expect(classify(probe(), resolved())).toEqual({ bucket: "ready", reason: "", include: true });
  });

  it("leaves a game already in the library unticked", () => {
    const verdict = classify(
      probe({ already_added: { app_id: "1", name: "Harbor Dash", same_file: true } }),
      resolved(),
    );
    expect(verdict).toMatchObject({ bucket: "check", include: false });
  });

  it("leaves a warned-about dump unticked, with the warning's first sentence", () => {
    const verdict = classify(
      probe({ track_warning: "This is one track of a disc. Send the .cue too." }),
      resolved(),
    );
    expect(verdict).toMatchObject({ bucket: "check", reason: "This is one track of a disc.", include: false });
  });

  it("ticks a name it could not confirm, and says so", () => {
    expect(classify(probe(), resolved({ title_source: "filename", match_kind: "none" })))
      .toMatchObject({ bucket: "check", include: true });
    expect(classify(probe(), null)).toMatchObject({ bucket: "check", include: true });
  });

  it("names the game a loose artwork match is for", () => {
    expect(
      classify(probe(), resolved({ match_kind: "index", title_source: "steamgriddb", art_game_name: "Harbor Dash 2" }))
        .reason,
    ).toBe("Artwork is for Harbor Dash 2");
  });

  it("does not repeat the title when the loose match named it", () => {
    expect(
      classify(probe(), resolved({ match_kind: "index", title_source: "libretro", art_game_name: "Harbor Dash" }))
        .reason,
    ).toBe("Close match");
  });
});
