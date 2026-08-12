import { callable } from "@decky/api";
import { type PreparedShortcut } from "./games";

/**
 * Games that arrive as a package: PlayStation 3, PlayStation 4 and Vita.
 */

/**
 * PlayStation 3 packages.
 *
 * A store PS3 game arrives as a `.pkg`, which is not a game until RPCS3 unpacks
 * it. That happens inside the normal add-a-game flow rather than in a panel of
 * its own — pick the .pkg like any ROM, and what gets added is the game.
 *
 * `installPs3Package` resolves when the unpack has finished, and emits
 * `ps3_install_progress` (name, text, percent) while it runs — the events fill
 * the bar and nothing depends on them arriving. It was the other way round
 * once, and a completion event that never arrived left the panel showing
 * "Unpacking" over an install that had finished five seconds earlier.
 *
 * Unpacking needs no window: RPCS3's `--headless --installpkg` does a 240MB
 * package in about five seconds with nothing on screen.
 */
export interface Ps3Package {
  name: string;
  path: string;
  size: number;
  /** From the package's own header, e.g. "NPUB30133". Empty if unreadable. */
  title_id: string;
  /** Whether RPCS3 already has this title unpacked. */
  installed: boolean;
}

export interface Ps3Game {
  title: string;
  title_id: string;
  /** What actually boots. */
  eboot: string;
  icon: string;
  background: string;
  /**
   * PS3 only: where this game's `.rap` stands, for games installed through
   * this plugin — the content id it needs is recorded at install time, since
   * an installed game does not carry one and the package is deleted. Empty
   * for anything installed another way, and for other consoles.
   */
  licence_state?: "installed" | "waiting" | "" | "unknown";
}

export const listPs3Packages = callable<[], { ok: boolean; packages: Ps3Package[] }>(
  "list_ps3_packages",
);
export const installPs3Package = callable<
  [path: string],
  {
    ok: boolean;
    error?: string;
    title?: string;
    title_id?: string;
    /** The .rap put in place alongside the game, if one came with it. */
    licence?: string;
  }
>("install_ps3_package");
export const listInstalledPs3Games = callable<[], { ok: boolean; games: Ps3Game[] }>(
  "list_installed_ps3_games",
);
/** Whatever id RPCS3 registered as — `emulators.save` suffixes on collision. */
export const ps3CoreId = callable<[], { ok: boolean; error?: string; core_id?: string }>(
  "ps3_core_id",
);

/**
 * PlayStation 4 packages, which take the same route with one difference:
 * shadPS4 cannot unpack one. The code that used to do it was taken out of
 * shadPS4 and published as a command-line tool, which this fetches the first
 * time it is needed. Emits `ps4_install_progress` while it runs.
 */
export const installPs4Package = callable<
  [path: string],
  { ok: boolean; error?: string; title?: string; title_id?: string }
>("install_ps4_package");
export const listInstalledPs4Games = callable<[], { ok: boolean; games: Ps3Game[] }>(
  "list_installed_ps4_games",
);
export const ps4CoreId = callable<[], { ok: boolean; error?: string; core_id?: string }>(
  "ps4_core_id",
);

/**
 * PS Vita titles Vita3K has installed.
 *
 * The one console here the plugin cannot install for you — Vita3K decrypts
 * content as it installs, so copying files in produces a game it lists and
 * cannot start. This reads what its interface produced.
 *
 * Launching is by title id rather than by path: `-Fr PCSA00011` boots a game
 * and handing Vita3K a path does not.
 */
export const listInstalledVitaGames = callable<[], { ok: boolean; games: Ps3Game[] }>(
  "list_installed_vita_games",
);
export const vitaCoreId = callable<[], { ok: boolean; error?: string; core_id?: string }>(
  "vita_core_id",
);
/**
 * Installs a Vita `.pkg` using the zRIF found beside it. Headless — Vita3K
 * does its own installing, so unlike PS4 there is no helper tool to fetch.
 * Emits `vita_install_progress` while it runs.
 */
export const installVitaPackage = callable<
  [path: string],
  { ok: boolean; error?: string; title?: string; title_id?: string }
>("install_vita_package");
export const prepareVitaGame = callable<
  [titleId: string],
  PreparedShortcut & { rom_path?: string; core_id?: string; title_id?: string }
>("prepare_vita_game");
/**
 * The unpacked PS3 or PS4 game a library entry points at, or `{ok: false}` —
 * the answer for every other system. The remove dialog asks about every game
 * and offers to delete the files only when this says yes; `system` says which
 * console answered, because a library entry does not record it.
 */
export const packagedGameInfo = callable<
  [romPath: string],
  {
    ok: boolean;
    /**
     * Which kind of thing removing the game could also delete: a game this
     * plugin unpacked inside an emulator, or a ROM it filed under its system.
     * One call because the dialog asks one question — both are gigabytes the
     * plugin put on disk and both cost a trip to another machine to replace.
     */
    kind?: "packaged" | "rom";
    system?: "ps3" | "ps4" | "vita";
    title_id?: string;
    title?: string;
    bytes?: number;
    /** ROMs only: every file that goes, including a cue sheet's tracks. */
    files?: string[];
    /** ROMs only: the system folder it is filed under, e.g. "snes". */
    folder?: string;
  }
>("packaged_game_info");
/** Deletes a filed ROM and its companions. Refuses anything outside the library. */
export const deleteRom = callable<
  [romPath: string],
  { ok: boolean; error?: string; freed?: number }
>("delete_rom");
/**
 * Deletes an unpacked game. The only thing in the plugin that removes something
 * playable, and it exists because these were unpacked by the plugin rather than
 * placed by the user: there is no file of theirs here to leave alone.
 */
export const deletePackagedGame = callable<
  [system: string, titleId: string],
  { ok: boolean; error?: string; freed?: number }
>("delete_packaged_game");
