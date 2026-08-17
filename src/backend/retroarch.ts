import { callable } from "@decky/api";
import { type Core } from "./games";
import { type RetroArchStatus } from "./emulators";

/**
 * RetroArch itself: what is installed, installing and removing it, and the
 * cores that go in it.
 *
 * Mirrors `installer.py` on the other side, which owns both halves for the same
 * reason: a core is downloaded from the buildbot into the RetroArch that was
 * found, so the question "what is installed" and the question "what can be
 * installed" are asked by the same panel one after the other.
 *
 * `Core` comes from games.ts rather than the other way round. What a core *is*
 * belongs to the add flow -- it is what a probe returns and what a game records
 * -- while this file is about putting one on the device.
 */

/** Re-detect and return the result. Nothing caches the answer across an await. */
export const refreshRetroArch = callable<[], RetroArchStatus>("refresh_retroarch");
export const getStatus = callable<[], RetroArchStatus>("get_status");
export const listCores = callable<[], Core[]>("list_cores");

/** A core from the libretro buildbot catalog, installed or not. */
export interface InstallableCore {
  id: string;
  display_name: string;
  system_name: string;
  databases: string[];
  extensions: string[];
  installed: boolean;
}

export type InstallCoreResult =
  | { ok: false; error: string }
  | {
      ok: true;
      core_id: string;
      path: string;
      info_written: boolean;
      cores_dir: string;
      core_count: number;
    };

export const listInstallableCores = callable<[refresh: boolean], InstallableCore[]>(
  "list_installable_cores",
);
export const suggestCoresForExtension = callable<[extension: string], InstallableCore[]>(
  "suggest_cores_for_extension",
);
export const installCore = callable<[coreId: string], InstallCoreResult>("install_core");
export const uninstallCore = callable<
  [coreId: string],
  { ok: boolean; error?: string; core_count?: number }
>("uninstall_core");

export const canInstallRetroArch = callable<[], { flatpak_available: boolean }>(
  "can_install_retroarch",
);
export const installRetroArch = callable<
  [],
  { ok: boolean; error?: string; started?: boolean }
>("install_retroarch");

/**
 * Why removal is or is not on offer. `reason` is written to be shown as-is:
 * a disabled button that does not say why is worse than no button.
 *
 * This comment had come adrift from the endpoint it describes and was sitting
 * above the RetroAchievements block, four declarations away, which is the sort
 * of thing that happens when a file is appended to rather than filed into.
 */
export const canUninstallRetroArch = callable<
  [],
  { ok: boolean; reason?: string; kind?: string; scope?: string }
>("can_uninstall_retroarch");

/** The boolean is `delete_data`, which is opt-in: those saves do not come back. */
export const uninstallRetroArch = callable<
  [boolean],
  { ok: boolean; error?: string; still_installed?: boolean; deleted_data?: boolean }
>("uninstall_retroarch");
