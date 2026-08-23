import { callable } from "@decky/api";

/**
 * Adding a game: probing a ROM, resolving its name and artwork, and the
 * shortcut that comes out.
 *
 * `Core` lives here rather than in retroarch.ts because this is where what a
 * core *is* matters -- it is what a probe returns and what a game records. That
 * file imports it to talk about installing one.
 */

export interface Core {
  id: string;
  path: string;
  display_name: string;
  /** The core's own name, e.g. "BlastEm". Prefer this when listing cores. */
  short_name: string;
  system_name: string;
  databases: string[];
  /**
   * A short label per entry in `databases`, in the same order — "Genesis",
   * "Game Gear". Sent from the backend because the name table is there: the
   * database name's own last word is "Mark III" for the Master System.
   */
  database_labels: string[];
  extensions: string[];
  has_info: boolean;
  /**
   * Whether the core publishes the memory map achievements are read from.
   * "yes" means it can take part, not that RetroAchievements has a set for a
   * given game; "unknown" means its .info file does not say, which is not a no.
   */
  cheevos: "yes" | "no" | "unknown";
  /** Set for registered standalone emulators, which are shaped like cores. */
  source?: "emulator";
}

export interface RomProbe {
  extension: string;
  /** What cores were matched against — the content extension inside archives. */
  match_extension: string;
  /** What to call this file in a sentence: ".iso", or a phrase when it has no extension. */
  what: string;
  /**
   * Whether this file can be unpacked here: a `.zip` sitting in the transfer
   * folder. False for a zip anywhere else, since that is the only directory an
   * archive's contents are written into.
   */
  can_unpack: boolean;
  /**
   * What is inside an archive nothing can run as it stands, by its header:
   * `"stfs"`, `"xex"`, or empty for an ordinary zip. When set, `matching_cores`
   * is deliberately empty — the alternative was offering the twenty-two cores
   * that claim `.zip` for a file none of them can read.
   */
  archived_content: string;
  is_archive: boolean;
  provisional_title: string;
  matching_cores: Core[];
  all_cores: Core[];
  suggested_core_id: string;
  unsupported_extension: boolean;
  /**
   * Which of its systems each core would take this file as, by core id. "" for
   * a core covering one system, and for a file whose extension names none —
   * `.cue` is a medium rather than a system. This is what preselects the
   * system row, so the answer is a default on screen rather than a guess.
   */
  system_for_core: Record<string, string>;
  /**
   * Set when the file is an Xbox disc image with no `default.xbe` at its root,
   * so there is nothing for the console to start. Said here because the console
   * says it so badly — "Please insert an Xbox disc" on a black screen reads as
   * a broken emulator long before it reads as a bad file. Absent for every
   * other kind of .iso; the backend only speaks when it is certain.
   */
  disc_warning?: string;
  /**
   * Set when a `.zip` turns out to be a PS Vita release rather than a zipped
   * ROM. `.zip` belongs to everyone — every zipped SNES and NES ROM has it —
   * so this is decided by looking inside for `sce_sys/param.sfo`, and absent
   * for every archive that is not one.
   */
  vita_release?: {
    vita: boolean;
    title: string;
    title_id: string;
    /** Whether the release brought its NoNpDrm `work.bin` licence with it. */
    licence: boolean;
  };
  /**
   * Present only for a `.pkg`: the one thing the picker can be pointed at that
   * is not a game yet. RPCS3 has to unpack it first, and what boots afterwards
   * is `dev_hdd0/game/<TITLE_ID>/USRDIR/EBOOT.BIN` — so the add flow installs
   * it and carries on with that path, and neither the product code nor the word
   * EBOOT is ever shown.
   */
  ps3_package?: PackageState;
  /**
   * The same, for PlayStation 4. `.pkg` does not say which console it is for —
   * a PS3 package begins \x7fPKG and a PS4 one \x7fCNT, and nothing else about
   * the file distinguishes them. Only one of these two is ever set.
   */
  ps4_package?: PackageState;
  /**
   * And PS Vita, which shares the PS3's `\x7fPKG` magic and differs only in a
   * type field. Only one of the three is ever set.
   */
  vita_package?: PackageState;
}

export interface PackageState {
  /** Catalog id of the emulator this console's packages install into. */
  emulator_id: string;
  /** Its display name, for saying which one is missing. */
  emulator_name: string;
  /**
   * Whether that emulator is registered yet.
   *
   * Reported with the package rather than found out by pressing install,
   * because that is a question worth answering *before* spending anything: a
   * PS4 package is several gigabytes and its `.pkg` is deleted on the way. The
   * panel offers to install the emulator when this is false.
   */
  emulator_ready: boolean;
  /**
   * Whether the emulator needs firmware before anything it launches will run.
   *
   * A static fact about the catalog entry, shown only while offering to install
   * it — there it answers "is installing this enough to play the game", which
   * for RPCS3 and Vita3K is no. Once the emulator exists the panel's own
   * firmware row takes over, keyed on the chosen core.
   */
  needs_firmware: boolean;
  title_id: string;
  /** Already unpacked, so `title` and `eboot` are filled and it can be added. */
  installed: boolean;
  /** From the game's own param.sfo, e.g. "Braid". Empty until it is installed. */
  title: string;
  eboot: string;
  /**
   * Vita only: whether the zRIF that decrypts this package was found beside
   * it. Vita3K cannot install without one and cannot derive it, so the panel
   * says so before the button rather than after the failure.
   */
  licence?: boolean;
  /**
   * Vita only: key files sitting in the folder that hold a zRIF but that
   * nothing ties to this package. Empty unless there are at least two — one on
   * its own is taken as the answer. This is the difference between "send the
   * key" and "say which of these is the key", and telling somebody to send a
   * file they have already sent is the worse of the two failures.
   */
  licence_candidates?: string[];
  /** Vita only: the filename that would resolve the above, e.g. `PCSA00011.zrif`. */
  licence_name?: string;
  /**
   * PS3 only: where this content's `.rap` is — `"installed"`, `"waiting"` (sent
   * but not yet put in place), or `""` (not here at all). Reported rather than
   * enforced, because licence-free packages boot without one; what it buys is
   * that "Failed to decrypt content" is no longer the first anyone hears of it.
   */
  licence_state?: "installed" | "waiting" | "" | "unknown";
  /**
   * PS3 only: the package's full content id, e.g.
   * `UP4049-NPUB30133_00-BRAID00000000001`. Reported because it *is* the
   * answer — RPCS3 reads a licence only under `<content id>.rap`, so naming
   * the file is more use than saying one is missing.
   */
  content_id?: string;
}

/** A downloaded image: `data` is a data URI, ready for both <img> and Steam. */
export interface ArtImage {
  data: string;
  kind: "png" | "jpg";
}

export interface ResolvedGame {
  title: string;
  system: string;
  matched_name: string;
  match_kind: "exact" | "index" | "none";
  art: Partial<Record<"capsule" | "header" | "hero" | "logo", ArtImage>>;
  art_source: "libretro" | "steamgriddb" | "none";
  /** The SteamGridDB title the art came from, so a wrong match is spottable. */
  art_game_name: string;
  core_id: string;
  rom_path: string;
}

export type PreparedShortcut =
  | { ok: false; error: string }
  | {
      ok: true;
      title: string;
      exe: string;
      start_dir: string;
      launch_options: string;
      launcher_path: string;
      core_path: string;
      collection_name: string;
      warn_flatpak_sdcard: boolean;
      /**
       * Where the ROM ended up, which is not where it was picked from if
       * adding it filed it out of the transfer folder and into one named after
       * its system. Register this rather than the path you sent, or the
       * library records a file that is no longer there.
       */
      rom_path?: string;
    };

/**
 * Per-game launch overrides.
 *
 * An absent field means "follow the global setting", which matters: a game left
 * alone still picks up a later change in Settings, while one that was overridden
 * deliberately keeps what it was given.
 */
export interface GameOptions {
  hide_osd?: "keep" | "startup" | "all";
  fullscreen?: boolean;
  /** Appended to the command line, parsed like a shell would. */
  extra_args?: string;
}

export interface AddedGame {
  app_id: number;
  title: string;
  rom_path: string;
  core_id: string;
  core_path: string;
  /** libretro database name; empty for emulators with no libretro system. */
  system: string;
  /** Short system label, e.g. "SNES" or "Switch". Preferred for display. */
  platform: string;
  launcher_path: string;
  /**
   * The Steam collection this game was filed into, recorded when it was added.
   *
   * Needed on the way out: removing the shortcut leaves the collection holding
   * an app id that no longer exists, so it never reads as empty and the shelf
   * outlives the last game on it. Absent for games added before this was
   * recorded, and for anyone who turned collections off.
   */
  collection?: string;
  options?: GameOptions;
}

/**
 * Controller shortcut that opens RetroArch's menu.
 *
 * RetroArch takes a fixed enum here, not a free-form binding, so these are the
 * only combos that exist. Kept in sync with `MENU_COMBOS` in launchers.py, which
 * owns the mapping to RetroArch's own numbers. Applies to libretro cores only --
 * a standalone emulator's menu binding is that emulator's business.
 */
export type MenuCombo =
  | "off"
  | "start_select"
  | "l1_r1_start_select"
  | "l3_r3"
  | "l1_r1"
  | "l3_r"
  | "l2_r2"
  | "down_select"
  | "down_y_l_r"
  | "hold_start"
  | "hold_select";

export interface PluginSettings {
  art_source: "auto" | "libretro" | "sgdb";
  hide_osd: "keep" | "startup" | "all";
  menu_combo: MenuCombo;
  add_to_collection: boolean;
  collection_name: string;
  collection_per_platform: boolean;
  collection_template: string;
  platform_names: "short" | "full";
  emulator_fullscreen: boolean;
  /**
   * Keep the transfer address the same between sessions so it can be bookmarked.
   *
   * Off by default: it turns the link into a standing credential that works
   * whenever the server runs, rather than one that dies with the session.
   */
  transfer_remember: boolean;
  last_rom_dir: string;
  last_core_by_ext: Record<string, string>;
  sgdb_api_key_set: boolean;
  /**
   * Show the dot on the Quick Access icon when a newer release exists.
   *
   * The dot is the only part of the update check that reaches somebody who did
   * not ask, so it is the only part with a switch. The row inside the panel and
   * the Updates tab are both places you went to look.
   */
  show_update_dot: boolean;
  /**
   * The one hidden shortcut that opens an emulator's own window, or 0.
   *
   * Not in the library: it is not a game, it is repointed rather than added to,
   * and only the frontend can create or remove a Steam shortcut. Declared here
   * because a reset has to take it away -- the backend deletes the record and
   * the script, and without this the shortcut is left behind pointing at
   * nothing.
   */
  setup_app_id: number;
}

/**
 * Libretro cores only, in the order a reader expects.
 *
 * `list_cores` deliberately returns registered standalone emulators alongside
 * real cores -- everything downstream treats them alike -- but a list headed
 * "installed cores" is not that place. Sorted by the name actually shown, since
 * the backend sorts by `display_name`, which carries a system prefix the reader
 * never sees ("Arcade (FinalBurn Neo)" sorting under A).
 */
export function realCores(cores: Core[]): Core[] {
  return cores
    .filter((core) => core.source !== "emulator")
    .sort((a, b) => a.short_name.localeCompare(b.short_name, undefined, { sensitivity: "base" }));
}

export const probeRom = callable<[romPath: string], RomProbe>("probe_rom");
/**
 * `title` overrides the name taken from the filename, for files that are not
 * named after the game. Every PS3 game installed from a package boots
 * `USRDIR/EBOOT.BIN`, so without it they would all search SteamGridDB for
 * "EBOOT"; the PARAM.SFO says "Braid".
 */
/**
 * `system` puts one of a multi-system core's databases at the front of the
 * artwork search, so the cover matches the shelf the game is going on. Without
 * it a Mega Drive ROM came back with the Game Gear cover of a same-named game.
 */
export const resolveGame = callable<
  [romPath: string, coreId: string, title?: string, system?: string],
  ResolvedGame
>("resolve_game");
export interface LibretroArtCandidate {
  name: string;
  system: string;
  score: number;
  url: string;
}

export interface SgdbArtCandidate {
  id: number;
  name: string;
  year: number;
  score: number;
}

export interface ArtCandidates {
  query: string;
  libretro: LibretroArtCandidate[];
  steamgriddb: SgdbArtCandidate[];
  sgdb_available: boolean;
}

export type AppliedArt =
  | { ok: false; error: string }
  | {
      ok: true;
      art: ResolvedGame["art"];
      art_source: "libretro" | "steamgriddb";
      art_game_name: string;
      /**
       * What the game should be called, if the caller has nothing better. The
       * picked name through the same tidier a filename goes through — a
       * libretro thumbnail is named like one, and "Super Mario World (USA)" is
       * the right artwork with the wrong shortcut name.
       */
      suggested_title: string;
    };

export const listArtCandidates = callable<
  [romPath: string, coreId: string, query: string],
  ArtCandidates
>("list_art_candidates");
/**
 * `pickedName` is the label on the row that was pressed. The SteamGridDB branch
 * asks its API for the name too, and that call answers nothing on any failure --
 * which produced artwork with no name, and a rename that did half of itself.
 */
export const applyArtCandidate = callable<
  [source: string, ref: string, system: string, pickedName: string],
  AppliedArt
>("apply_art_candidate");

/**
 * `system` is the database resolveGame settled on. It only matters for a core
 * covering more than one — Dolphin declares GameCube and Wii — where the first
 * one would otherwise decide the collection and file every Wii game as GameCube.
 */
/**
 * `titleId` is for emulators that start an installed title rather than a file
 * — Vita3K, whose launcher takes `-r PCSA00011`. Ignored by every other, and
 * empty for every game picked as a file.
 */
export const prepareShortcut = callable<
  [title: string, coreId: string, romPath: string, system: string, titleId?: string],
  PreparedShortcut
>("prepare_shortcut");
/**
 * `rememberCore` is what makes the next ROM of the same kind suggest this core.
 * Pass false for a PS3 game: what boots is EBOOT.BIN, and remembering it would
 * file `.bin` under RPCS3 and suggest a PS3 emulator for the next PS1 disc.
 *
 * `collection` is the shelf the game was actually filed onto — "" when filing
 * was not attempted or did not take. Omit it only if you have not tried yet;
 * the backend then records where the game *belongs*, which is a guess. Go
 * through `addPreparedGame` rather than calling this directly.
 */
export const registerGame = callable<
  [
    appId: number,
    title: string,
    romPath: string,
    coreId: string,
    launcherPath: string,
    system: string,
    rememberCore?: boolean,
    collection?: string,
  ],
  AddedGame
>("register_game");
export type UpdatedGame =
  | { ok: false; error: string }
  | {
      ok: true;
      title: string;
      rom_path: string;
      rom_changed: boolean;
      exe: string;
      start_dir: string;
      launcher_changed: boolean;
      collection: string;
      /** Where it was filed before, so the caller can move it out. */
      previous_collection: string;
      platform: string;
    };

/** `romPath` empty keeps the current ROM; `options` replaces the overrides. */
/**
 * `system` refiles a game onto another of its core's systems. Empty means the
 * edit says nothing about it and the stored answer stands — renaming a Wii game
 * must not move it to GameCube. It is the only way to correct a game filed
 * under the wrong system without deleting and re-adding it.
 */
export const updateGame = callable<
  [
    appId: number,
    title: string,
    coreId: string,
    romPath: string,
    options: GameOptions,
    system?: string,
  ],
  UpdatedGame
>("update_game");
/**
 * What a collection name made by this plugin looks like, for recognising the
 * ones it left behind empty. See `collection_shape` and `ownedCollectionMatcher`.
 */
/** The pieces a collection name is built from, as the settings have them. */
export interface CollectionShape {
  base: string;
  per_platform: boolean;
  template: string;
  /**
   * Collections this plugin has actually filed a game into, whatever the
   * settings said at the time. The fields above can only describe shelves the
   * *current* naming would produce, so they lose every one made under a naming
   * since changed; these are the ones it knows it made.
   */
  known?: string[];
}
export const collectionShape = callable<[], CollectionShape>("collection_shape");
/** One offered naming format, and the name it would actually produce. */
export interface CollectionTemplate {
  template: string;
  /**
   * Rendered by the backend, using the same function that names a real
   * collection — so a preview cannot promise a format the filing does not use.
   * Holds a real newline where the format asks for one.
   */
  preview: string;
}
export const collectionTemplates = callable<[], { templates: CollectionTemplate[] }>(
  "collection_templates",
);
/**
 * Stop claiming collections, because they have been deleted. Keeps the record
 * from growing forever and from coming to claim a shelf somebody later makes by
 * hand under a name this plugin once used.
 */
export const forgetCollections = callable<
  [names: string[]],
  { ok: boolean; forgotten: string[] }
>("forget_collections");
export const unregisterGame = callable<[appId: number], AddedGame | null>("unregister_game");
export const listAdded = callable<[], AddedGame[]>("list_added");

/**
 * Everything the backend forgot, so the caller can undo the Steam side.
 *
 * Reported rather than acted on because the backend cannot touch Steam, and it
 * has to be reported *before* the records are deleted -- afterwards nothing
 * remembers which apps or collections were involved.
 */
export interface ClearedLibrary {
  ok: boolean;
  games: Array<{ app_id: number; title: string; collection: string }>;
  collections: string[];
  launchers_deleted: number;
  /** Bytes recovered by deleting the games themselves, ROMs and installs alike. */
  freed: number;
}

/**
 * Emits `clear_library_progress` (text, percent 0-100) while it runs.
 *
 * The percentages cover the backend's own work only, and it is not all of the
 * work: the caller still has to empty the collections and remove the shortcuts
 * afterwards. See `LibraryPanel`, which folds this into a scale that includes
 * those.
 */
export const clearLibrary = callable<[], ClearedLibrary>("clear_library");

/**
 * What was already running when this game's launcher refused to start.
 *
 * The launch gate lives in the generated launcher script, because that is the
 * last place that can decide not to start a game: Steam will not warn before
 * launching one of these over another -- its check is gated on an `app_type` a
 * non-Steam shortcut does not carry -- and neither of the two Steam calls that
 * look like they would stop a launch actually does. `launchers.py` has the
 * measurements.
 *
 * So the script decides and this reports the decision. Asking rather than
 * predicting is the point: the dialog appears for a launch that really was
 * stopped, so it can never be shown over a game that started anyway.
 *
 * `others` is the space-separated app ids the script saw. Consumed by reading.
 */
export interface LaunchBounce {
  bounced: boolean;
  others: string;
}

export const launchBounced = callable<[appId: number], LaunchBounce>("launch_bounced");

/** Let one launch past the gate, after the user has said to. */
export const approveLaunch = callable<[appId: number], { ok: boolean }>("approve_launch");
