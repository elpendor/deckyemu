import { callable } from "@decky/api";

/**
 * Emulators: what is installed, the one-click catalog, and hand-registered ones.
 */

/** Whether this is a Steam Deck, and whether the user waived the answer. */
export interface DeviceState {
  /** Valve hardware. The only field anything should branch on for "is a Deck". */
  supported: boolean;
  /** `supported`, or the user turned the override on. Gates the whole UI. */
  allowed: boolean;
  /** The override is on. Distinguishes "fine" from "continuing anyway". */
  waived: boolean;
  /** "Steam Deck (OLED)", or the vendor and product this machine reported. */
  model: string;
  /** "deck" | "valve-unknown" | "not-valve" | "unknown" -- picks the wording. */
  why: string;
}

export interface RetroArchStatus {
  found: boolean;
  kind: "" | "flatpak" | "native" | "appimage";
  exe: string;
  config_dir: string;
  core_count: number;
  core_dirs: string[];
  /** Custom standalone emulators; the plugin is usable with these alone. */
  emulator_count: number;
  default_rom_dir: string;
  /**
   * The transfer folder when a sent file is still sitting in it unadded, else "".
   *
   * Takes precedence over `last_rom_dir` in the picker: a file waiting in the
   * inbox says more about what the user is here to do than where they browsed
   * last time. Empty the rest of the time, which is most of it -- adding a game
   * moves its ROM out, so the folder empties itself.
   */
  waiting_rom_dir: string;
  /** The user's home, resolved by the backend. Never hardcode /home/deck. */
  home_dir: string;
  /**
   * What machine this is, and whether the plugin will do anything on it.
   *
   * Carried here rather than fetched separately because the panel cannot render
   * until it knows: a second round trip would only be a chance to show the real
   * UI for a moment on hardware that is not meant to have it.
   *
   * Optional because a backend older than this field is a real thing during an
   * update, and `undefined` has to read as "supported" -- refusing to render on
   * a Deck because the answer had not arrived would be a far worse bug than the
   * one this exists to prevent.
   */
  device?: DeviceState;
}

/** A user-registered standalone emulator, e.g. Dolphin or PCSX2. */
export interface CustomEmulator {
  id: string;
  name: string;
  kind: "flatpak" | "path";
  target: string;
  args: string;
  extensions: string[];
  /** libretro system names, which is what makes artwork lookup work. */
  databases: string[];
  /** Label for systems with no libretro database, used in collection names. */
  platform: string;
  platform_full: string;
  /** Switch appended when "launch fullscreen" is on; differs per emulator. */
  fullscreen_args: string;
  /**
   * Whether this was registered by installing a catalog entry rather than
   * described by hand. Derived by the backend from `catalog_recipe`; it is what
   * lets a registered row explain why it also appears in the catalog list.
   */
  from_catalog: boolean;
  /**
   * Anything worth saying about fixes that are still switched on.
   *
   * Shown on the Emulators tab rather than left in the editor: the thing to do
   * about either kind is update the emulator, and a message nobody opens is not
   * a message. Empty for almost every emulator, almost always.
   */
  fix_notices?: FixNotice[];
}

export interface SystemOption {
  id: string;
  /** Empty for systems libretro has no database for (Switch, Wii U, PS3…). */
  database: string;
  /** Full "Manufacturer - System" name, shown in the picker. */
  label: string;
  short: string;
  full: string;
  /** False when artwork can only come from SteamGridDB. */
  libretro: boolean;
}

export const listEmulators = callable<[], CustomEmulator[]>("list_emulators");
export const listSystems = callable<[], SystemOption[]>("list_systems");
/** Extensions arrive as free text from the editor and are parsed server-side. */
/** A workaround this emulator still has on that its own release has retired. */
/**
 * Something to say about a fix the user asked for and is not fully getting.
 *
 * `retired` — the emulator has since fixed this itself, so the fix is redundant.
 * `unavailable` — the fix edits the emulator's binary and this build would not
 * take the edit, so it is not running at all. Both mean "update the emulator";
 * neither is ever raised for a fix that is switched off or working.
 */
export interface FixNotice {
  id: string;
  name: string;
  state: "retired" | "unavailable";
  /** The same sentence the row and the dialog show. */
  note: string;
}

export interface EmulatorInput {
  id?: string;
  name: string;
  kind: "flatpak" | "path";
  target: string;
  args: string;
  extensions: string | string[];
  databases: string[];
  platform?: string;
  platform_full?: string;
  fullscreen_args?: string;
}

export const saveEmulator = callable<
  [emulator: EmulatorInput],
  { ok: boolean; error?: string; emulator?: CustomEmulator; notice?: string }
>("save_emulator");
export const suggestLaunchOptions = callable<
  [target: string],
  { args: string; fullscreen_args: string }
>("suggest_launch_options");
/** One correction an emulator carries that the user is allowed to decline. */
export interface Workaround {
  id: string;
  name: string;
  /** The bug being compensated, in one sentence. */
  because: string;
  /** What switching it on gives up, in the user's terms. */
  costs: string;
  /** The issue or pull request that will make it unnecessary. */
  upstream: string;
  enabled: boolean;
  default: boolean;
  /**
   * What is up with this fix, or "" when nothing is.
   *
   * `retired` — the installed build of the emulator has the fix, so this is
   * redundant. `unavailable` — this build would not take the fix, so it is
   * switched on and doing nothing. Both are *observed*: retired is the build
   * in front of us compared against the one that fixed it, never a claim
   * shipped with the plugin.
   *
   * Neither ever changes what the switch will do. It always works, both ways.
   */
  state: "" | "retired" | "unavailable";
  /** The one sentence for `state`, worded once and shown everywhere. */
  note: string;
  /**
   * Whether this fix edits the emulator's own files rather than only its
   * launch. Derived from the catalog, so the panel explains it for every such
   * fix without an author having to remember to write it down.
   */
  patches: boolean;
}

export const listWorkarounds = callable<
  [emulatorId: string],
  { ok: boolean; error?: string; workarounds?: Workaround[] }
>("list_workarounds");
export const setWorkaround = callable<
  [emulatorId: string, workaroundId: string, enabled: boolean],
  { ok: boolean; error?: string }
>("set_workaround");

export const removeEmulator = callable<
  [emulatorId: string],
  { ok: boolean; error?: string }
>("remove_emulator");
