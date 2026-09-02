import { callable } from "@decky/api";

/**
 * Firmware: what an emulator still needs, and putting it where it reads it.
 */

/** A file the emulator needs and this plugin will never supply. */
export interface FirmwareRequirement {
  name: string;
  note: string;
  /**
   * The filenames that will actually be recognised, in words. Without it the
   * naming rule is invisible — a PS2 BIOS under any other name is simply never
   * matched, with nothing said about why.
   */
  expects: string;
}

/** One requirement, resolved against what is sitting in the firmware folder. */
export interface FirmwareState {
  name: string;
  note: string;
  /** Which filenames are recognised, in words. */
  expects: string;
  /** Set when the user must import the file through the emulator; says how. */
  manual: string;
  /** Where it would be copied to. Shown so a wrong path is visible. */
  dest: string;
  /** Matching files present but not yet in place. */
  waiting: string[];
  /**
   * What is already in place. Filenames for a copied requirement; for an
   * imported one, what the emulator produced — RPCS3 reports "4.93".
   */
  installed: string[];
  /** Of those, the ones this plugin did not put there. */
  foreign: string[];
  can_install: boolean;
  /**
   * Whether taking it back out is offered. For an imported requirement this
   * means deleting the tree the emulator unpacked — offered only where the
   * catalog names that tree, since "delete several thousand files somewhere
   * under here" is not a promise worth guessing at.
   */
  can_remove: boolean;
  /** The emulator unpacks this one itself, unattended, when Install is pressed. */
  imported: boolean;
  /**
   * This one is not a dump, so it can be downloaded rather than asked for.
   * Only xemu's blank Xbox disk image qualifies: an empty formatted disk
   * published by xemu's own project, without which xemu cannot start at all.
   */
  can_fetch: boolean;
  /**
   * Whether it could be fetched at all, installed or not. `can_fetch` answers
   * "show the download button" and goes false once it is in place; this
   * answers "is putting it back a press, or another trip to a PC" — which is
   * what the remove dialog has to promise.
   */
  fetchable?: boolean;
  /**
   * Whether a game boots without it. Only RPCS3's .rap row is optional: a
   * licence belongs to one game rather than to the emulator.
   */
  optional?: boolean;
  /**
   * Whether "not installed" is a fact or just the absence of a way to tell.
   * False means unknown, which must never be presented as missing.
   */
  detectable?: boolean;
  /** Removal deletes a directory the emulator wrote, not a file we copied. */
  tree?: boolean;
  /**
   * Installing means opening the emulator's own window at the file, because
   * the emulator offers no other way. Same button, different thing behind it.
   */
  gui_install?: boolean;
  /** What the user is about to be asked for, said before the window opens. */
  prompt?: string;
  /**
   * Installed state read from a folder the emulator filled, so `installed`
   * holds a state rather than a list of filenames.
   */
  detected?: boolean;
}

export interface FirmwareReport {
  /** The folder files are sent to. */
  path: string;
  emulators: Array<{ id: string; name: string; requirements: FirmwareState[] }>;
}

/**
 * An emulator that can be installed from the panel in one press.
 *
 * `extensions` is derived from libretro's own metadata rather than stored, so it
 * arrives resolved and there is nothing for the user to type.
 */
export interface CatalogEmulator {
  id: string;
  name: string;
  summary: string;
  /** Extra warning about how this one takes its ROM, when it has one. */
  note: string;
  /**
   * "byo" -- bring your own -- is an emulator this plugin describes but will
   * not install or link to. The user points at a binary they obtained
   * themselves and the entry supplies everything else.
   */
  kind: "flatpak" | "github" | "byo";
  /** Full system name, e.g. "PlayStation 2". */
  system: string;
  short: string;
  extensions: string[];
  /**
   * False when the launch arguments are a best reading of the documentation
   * rather than confirmed behaviour. Several emulators ignore unknown arguments
   * silently, so a wrong recipe opens the emulator without the game and looks
   * like nothing happened.
   */
  verified: boolean;
  firmware: FirmwareRequirement[];
  /**
   * The motion server, for the emulators that read the Deck's gyro over a local
   * socket. `declared` is false for every other emulator, which is most of them.
   *
   * `waiting` is seconds until the next download attempt, and is what makes a
   * rate-limited address readable as "not yet" rather than "broken".
   */
  motion: {
    declared: boolean;
    ready: boolean;
    /**
     * False when the binary is here but the emulator is not pointed at it —
     * which happens when the user owns its controller config, so the
     * settings this plugin writes are correctly refused.
     */
    configured: boolean;
    waiting: number;
  };
  /** Whether the emulator is actually present, not merely registered. */
  installed: boolean;
  present: boolean;
  registered: boolean;
  /** "system" means it was installed for all users and cannot be removed here. */
  scope: string;
  /**
   * True when this entry came from a definition the user imported rather than
   * from the plugin. Shown, because nobody here has tested that recipe and
   * saying so is the honest half of allowing imports at all.
   */
  imported: boolean;
  /** The definition's filename, for an imported entry. */
  source_file: string;
  /** Where a "byo" emulator's binary is, once located. */
  target?: string;
}

/** One user-supplied definition on disk. */
export interface ImportedEmulator {
  id: string;
  name: string;
  summary: string;
  file: string;
}

export const importedEmulators = callable<
  [],
  {
    entries: ImportedEmulator[];
    /** Why definitions were refused. A refused one produces no emulator at
     * all, which on its own is indistinguishable from sending the wrong file. */
    problems: string[];
    /** The filename suffix the transfer panel offers to import. */
    suffix: string;
  }
>("imported_emulators");
/**
 * What a definition says it will do, without storing it.
 *
 * Shown and confirmed before importing. A definition is a list of actions the
 * plugin performs, and the person importing it is the only one who can judge
 * whether they trust its author -- so they see what it installs and where it
 * writes first.
 */
export const previewEmulatorDefinition = callable<
  [name: string],
  {
    ok: boolean;
    error?: string;
    id?: string;
    name?: string;
    summary?: string;
    system?: string;
    /** What it will download, or "" when you supply the binary yourself. */
    installs?: string;
    /** Every directory it is allowed to write into. */
    writes?: string[];
    /** True when a definition with this id is already imported. */
    replaces?: boolean;
  }
>("preview_emulator_definition");

/** A definition file sitting in the transfer folder. */
export interface DefinitionFile {
  name: string;
  size: number;
  /** Modified time, seconds since the epoch. Newest first. */
  at: number;
}

/**
 * What is waiting to be imported, read off the transfer folder.
 *
 * Deliberately not the transfer dialog's received list, which holds what this
 * session took delivery of: a definition sent before the last reload is still
 * on the device and still importable, and was previously unreachable.
 */
export const listEmulatorDefinitions = callable<
  [],
  { ok: boolean; suffix: string; path: string; files: DefinitionFile[] }
>("list_emulator_definitions");
/** Imports a definition sitting in the transfer folder, by its filename. */
export const importEmulatorDefinition = callable<
  [name: string, replace?: boolean],
  { ok: boolean; error?: string; id?: string; name?: string }
>("import_emulator_definition");
export const removeImportedEmulator = callable<
  [entryId: string],
  { ok: boolean; error?: string }
>("remove_imported_emulator");
/** Points a "byo" entry at a binary the user already has. */
export const locateEmulator = callable<
  [entryId: string, path: string],
  { ok: boolean; error?: string; notice?: string }
>("locate_emulator");

export const listEmulatorCatalog = callable<[], CatalogEmulator[]>("list_emulator_catalog");
/** Resolves once the install has *started*; watch the events for the rest. */
export const installEmulator = callable<
  [entryId: string],
  { ok: boolean; started?: boolean; error?: string }
>("install_emulator");
/**
 * `deleteData` removes the emulator's own directory with it — saves,
 * configuration, memory cards. Off unless asked for, and it only applies to a
 * flatpak: that is the kind whose `~/.var/app/<id>` outlives the application,
 * so a reinstall otherwise inherits the last install's state.
 */
export const uninstallEmulator = callable<
  [entryId: string, deleteData?: boolean],
  { ok: boolean; error?: string }
>("uninstall_emulator");

/** One installed emulator whose version can be moved. */
export interface EmulatorBuild {
  id: string;
  name: string;
  app_id: string;
  /**
   * How it was installed. `flatpak` can be held; `github` cannot and does not
   * need to be — nothing outside this plugin updates an AppImage it downloaded.
   */
  channel: "flatpak" | "github";
  /**
   * Short commit, or a release tag. Empty for an AppImage installed before the
   * build was recorded, which reads as unknown rather than being guessed.
   */
  build: string;
  /**
   * `unknown` is a real answer, not a quiet `current`. A flatpak is always one
   * of the other two — one `remote-ls --updates` covers every emulator at once.
   * An AppImage stays `unknown` until `checkEmulatorUpdates` has run, because
   * finding out costs a call to somebody else's repository.
   */
  update_state: "unknown" | "current" | "available";
  /** Pinned, so no update will move it. */
  held: boolean;
  /** Non-empty when the version cannot be changed, and why. */
  reason: string;
}

/**
 * Installed emulators whose build can be changed, and where each one is.
 *
 * Two flatpak queries however many emulators there are, and for AppImages the
 * answer recorded by the last `checkEmulatorUpdates` — so this is cheap enough
 * to call when the tab opens and makes no network call of its own.
 */
export const emulatorBuilds = callable<[], EmulatorBuild[]>("emulator_builds");

/**
 * Ask each installed AppImage emulator's project what it has published.
 *
 * One network call per installed AppImage emulator, against repositories that
 * are not ours, so this is only ever run from a button — never on open, never
 * per row. `emulatorBuilds` reads back what it found.
 *
 * `error` names the projects that could not be reached; their previous answers
 * are left alone rather than blanked, so a failed check costs a row nothing.
 */
export const checkEmulatorUpdates = callable<
  [],
  { ok: boolean; checked: number; available: number; error: string }
>("check_emulator_updates");

/** One past build of an emulator, as offered to go back to. */
export interface PastBuild {
  /** Full commit hash, or a release tag. Passed back verbatim to `rollbackEmulator`. */
  commit: string;
  /** `2026-07-26 20:53:49 +0000` from flatpak, or `2026-08-10` from a release. */
  date: string;
  /** The commit subject or the asset's filename — what makes this choosable. */
  subject: string;
  current: boolean;
  /** Bytes, for a release. Absent for a flatpak build, which costs a call each. */
  size?: number;
  /** A release the project marked as not final. */
  prerelease?: boolean;
}

/** Costs a network round trip, so ask when the list is opened, not per row. */
export const emulatorBuildList = callable<
  [entryId: string],
  { ok: boolean; error?: string; builds: PastBuild[] }
>("emulator_build_list");

/**
 * What flatpak knows about one build.
 *
 * There is no changelog behind this — a Flathub commit carries a one-line
 * subject describing a packaging change and nothing more. What it is for is
 * `download`: switching build re-fetches the whole app, which is a few hundred
 * megabytes, and the list has no room to say so.
 *
 * Sizes arrive formatted by flatpak (`409.0 MB`), not as numbers.
 */
export interface BuildDetails {
  version?: string;
  license?: string;
  download?: string;
  installed?: string;
  subject?: string;
  date?: string;
  commit?: string;
  parent?: string;
}

/** One call per build, made when a row is opened rather than for the whole list. */
export const emulatorBuildDetails = callable<
  [entryId: string, commit: string],
  { ok: boolean; error?: string; details: BuildDetails }
>("emulator_build_details");

/** Resolves once the update has *started*; watch the install events for the rest. */
export const updateEmulator = callable<
  [entryId: string],
  { ok: boolean; started?: boolean; error?: string }
>("update_emulator");

/**
 * Move an emulator back to a past build and pin it there.
 *
 * Pinning is part of the same action on purpose: an unpinned downgrade is undone
 * by the next update, and nothing would connect a game breaking a week later to
 * a version change nobody asked for. Watch the install events — and read the
 * done event's message, which is non-empty when the move worked but the pin did
 * not.
 */
export const rollbackEmulator = callable<
  [entryId: string, commit: string],
  { ok: boolean; started?: boolean; error?: string }
>("rollback_emulator");

/** Pin an emulator at its current build, or let it move again. */
export const holdEmulator = callable<
  [entryId: string, held: boolean],
  { ok: boolean; held?: boolean; error?: string }
>("hold_emulator");
/**
 * Registers an emulator that is already on the device. Needed because installed
 * and registered come apart: Discover and the usual emulation setups install
 * these same flatpaks, and one installed that way has no extensions and never
 * appears when adding a game until it is registered here.
 */
export const registerEmulator = callable<
  [entryId: string],
  { ok: boolean; error?: string; notice?: string }
>("register_emulator");
/**
 * The launcher that opens an emulator's own interface, with no game.
 *
 * Some jobs only exist behind those windows -- installing PS3 firmware and PKG
 * games, importing Switch firmware -- and gamescope only shows a window when
 * Steam launched the process, so a shortcut is the only way to see one.
 * `appId` is a shortcut already made for this emulator, or 0.
 */
export const prepareEmulatorGui = callable<
  [entryId: string],
  {
    ok: boolean;
    error?: string;
    title?: string;
    exe?: string;
    start_dir?: string;
    app_id?: number;
  }
>("prepare_emulator_gui");
/**
 * Remember the one shortcut that opens any emulator's own window.
 *
 * One rather than one per emulator. gamescope composites nothing Steam did not
 * launch, so a shortcut is the only route to an emulator's UI — but it is a door
 * used once to install firmware and never again, and one permanent library entry
 * per emulator is a poor trade for that. This one is repointed at whichever
 * emulator is being opened, and hidden.
 */
export const recordSetupShortcut = callable<[appId: number], { ok: boolean }>(
  "record_setup_shortcut",
);

export const firmwareDir = callable<[], { path: string }>("firmware_dir");
export const firmwareStatus = callable<[], FirmwareReport>("firmware_status");
/**
 * Puts one requirement where the emulator wants it.
 *
 * Usually a move into the destination folder. For an imported requirement the
 * emulator does the work itself — RPCS3 unpacks a PS3 firmware PUP in about six
 * seconds with no window — and `installed` then says what it produced, with the
 * source file deleted only once that has been confirmed.
 */
export const installFirmware = callable<
  [entryId: string, requirement: string],
  {
    ok: boolean;
    error?: string;
    copied?: string[];
    kept?: string[];
    installed?: string[];
    deleted?: string[];
    dest?: string;
    /** The setting now pointing at the installed file, e.g. "hdd_path". */
    configured?: string;
    config_error?: string;
  }
>("install_firmware");
/**
 * Downloads a prerequisite that is nobody's dump. The rule is enforced in the
 * backend: a requirement without a fetch source is refused rather than quietly
 * downloaded from somewhere.
 */
export const fetchFirmware = callable<
  [entryId: string, requirement: string],
  {
    ok: boolean;
    error?: string;
    copied?: string[];
    dest?: string;
    configured?: string;
    config_error?: string;
  }
>("fetch_firmware");
/**
 * Take a requirement's files back out of the emulator, so Install can be run
 * again. Leaves the transfer folder alone, so nothing is lost that a second
 * Install cannot put back.
 */
export const uninstallFirmware = callable<
  [entryId: string, requirement: string],
  {
    ok: boolean;
    error?: string;
    removed?: string[];
    foreign?: string[];
    dest?: string;
    /** Bytes recovered. Only an imported requirement reports one — it is the
     *  only removal where the amount is worth saying. */
    freed?: number;
  }
>("uninstall_firmware");
// The development-only reset calls are declared in DevPanel.tsx rather than
// here. `callable(...)` runs at module scope, so rollup keeps it as a side
// effect and three unused RPC stubs were surviving into release bundles that
// contained no way to reach them. Declared beside their only caller, they are
// dropped with it.

/**
 * Opens an emulator's own window with the firmware file already chosen.
 *
 * For the one requirement with no unattended route: Ryujinx reads
 * `--install-firmware` inside its main window and then waits on a Yes/No
 * dialog, so the window and the press are both unavoidable. This removes the
 * file browser between them. Reuses the emulator's existing setup shortcut.
 */
export const prepareFirmwareGui = callable<
  [entryId: string, requirement: string],
  {
    ok: boolean;
    error?: string;
    title?: string;
    exe?: string;
    start_dir?: string;
    app_id?: number;
    file?: string;
  }
>("prepare_firmware_gui");
/**
 * What the emulator behind a core still needs before a game will boot.
 *
 * Asked while a game is being added — the last moment anything can be said.
 * Empty for libretro cores: RetroArch has its own system directory and its own
 * rules, and a warning derived from guesswork is one nobody can act on.
 */
export const missingFirmware = callable<
  [coreId: string],
  {
    ok: boolean;
    emulator?: string;
    missing?: { name: string; waiting: boolean }[];
  }
>("missing_firmware");
/** Deletes from the firmware folder only; never touches an installed copy. */
/**
 * Throw away sent firmware the emulator has already taken in.
 *
 * Called as the panel loads rather than offered as a button: the requirement
 * it covers is installed through the emulator's own window, so there is no
 * result to act on at the time and the panel reopening is the next moment the
 * question can be asked at all.
 */
export const tidyFirmware = callable<
  [],
  { ok: boolean; error?: string; removed?: string[] }
>("tidy_firmware");

export const deleteFirmware = callable<
  [names: string[]],
  { ok: boolean; error?: string; removed?: string[]; missing?: string[] }
>("delete_firmware");

/**
 * One helper binary this plugin fetches for an emulator that needs a second
 * program — the motion server, the PS4 package extractor.
 *
 * Deliberately not a `FirmwareRequirement`. That list is the user's own dumps
 * and promises that nothing on it is ever downloaded; these are the opposite,
 * and the two are kept apart so each can say plainly where its contents come
 * from.
 */
export interface HelperTool {
  name: string;
  label: string;
  /** The project it comes from, shown so nobody has to trust an unnamed binary. */
  repo: string;
  /** What it does, in a sentence. A label alone explains nothing. */
  why: string;
  /** Emulators that want it, which is the whole of why the row exists. */
  needed_by: string[];
  installed: boolean;
  path: string;
  size: number;
  /** False when no emulator that wants it is installed: not missing, just not needed. */
  wanted: boolean;
  /** Seconds until the next download attempt, when one is being waited out. */
  waiting: number;
}

export const toolsStatus = callable<[], { tools: HelperTool[] }>("tools_status");
export const installHelperTool = callable<[name: string], { ok: boolean; error?: string; path?: string }>(
  "install_helper_tool",
);
export const removeHelperTool = callable<[name: string], { ok: boolean; error?: string }>(
  "remove_helper_tool",
);
