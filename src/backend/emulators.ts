import { callable } from "@decky/api";

/**
 * Emulators: what is installed, the one-click catalog, and hand-registered ones.
 */

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
export const removeEmulator = callable<
  [emulatorId: string],
  { ok: boolean; error?: string }
>("remove_emulator");
