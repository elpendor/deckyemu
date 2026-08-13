import { callable } from "@decky/api";
import { type PluginSettings, type PluginVersion } from "./games";

/**
 * Everything after a game is added: settings, updates, collections, the
 * library audit, and the file transfer server.
 */

export const pluginVersion = callable<[], PluginVersion>("plugin_version");

/** A release the plugin could install, as found on GitHub. */
export interface ReleaseInfo {
  version: string;
  tag: string;
  notes: string;
  asset_url: string;
  asset_name: string;
  /** From the release body, for decky to verify the download. "" if absent. */
  sha256: string;
  prerelease: boolean;
  published_at: string;
}

export interface UpdateCheck {
  available: boolean;
  current: string;
  /**
   * Whether the request succeeded — not whether it found anything. A repository
   * with nothing published is a successful check that found nothing, and
   * conflating the two reported GitHub as unreachable when it had answered.
   */
  checked: boolean;
  /** Why it failed, when it did. Empty on success. */
  error: string;
  /** How many installable releases exist. */
  count: number;
  latest?: ReleaseInfo;
}

/** Only looks; decky's loader does the installing. See src/updater.ts. */
export const checkForUpdate = callable<[force: boolean], UpdateCheck>("check_for_update");

/**
 * Download the release here and offer it to decky on loopback.
 *
 * Decky fetches the URL itself and has no credentials. The returned URL is local
 * and needs none, which also keeps a private repository's asset -- which decky
 * would 404 on -- installable.
 */
export const stageUpdate = callable<
  [],
  { ok: boolean; error?: string; url?: string; version?: string; sha256?: string }
>("stage_update");

export const getSettings = callable<[], PluginSettings>("get_settings");
export const setSettings = callable<[patch: Record<string, unknown>], PluginSettings>(
  "set_settings",
);
export const validateSgdbKey = callable<
  [apiKey: string],
  { ok: boolean; error?: string }
>("validate_sgdb_key");
export const findExistingSgdbKey = callable<[], { found: boolean; source: string }>(
  "find_existing_sgdb_key",
);
export const importExistingSgdbKey = callable<
  [],
  { ok: boolean; error?: string; how?: string }
>("import_existing_sgdb_key");
export interface CollectionMigrationPlan {
  moves: Array<{ app_id: number; title: string; from: string; to: string }>;
}

export const planCollectionMigration = callable<
  [previous: Partial<PluginSettings> | null],
  CollectionMigrationPlan
>("plan_collection_migration");
export const collectionTargets = callable<
  [],
  { targets: Record<string, string>; titles: Record<string, string> }
>("collection_targets");
export const recordCollections = callable<
  [assignments: Record<string, string>],
  { ok: boolean; recorded: number }
>("record_collections");
export interface AuditRecord {
  app_id: number;
  title: string;
  rom_path: string;
  launcher_path: string;
}

export interface AuditReport {
  registry: AuditRecord[];
  broken: Array<AuditRecord & { reasons: string[] }>;
  strays: string[];
  /**
   * ROMs filed under a system that no game points at. Removing a game offers
   * to delete its ROM and defaults to keeping it, so they accumulate — and a
   * shortcut deleted in Steam itself never reaches that dialog at all.
   */
  unused_roms: Array<{ path: string; name: string; system: string; bytes: number }>;
  /**
   * Shortcuts of ours that the registry does not account for.
   *
   * Read from Steam's own shortcuts.vdf rather than from anything the plugin
   * keeps, which is the point: a reset deletes the registry and the launcher
   * scripts, and Steam's shortcuts outlive both. Every other check here starts
   * from a registry entry, so that pair was invisible.
   *
   * `dead` — the launcher is gone, so it cannot start anything.
   * `duplicate` — a registered game already runs this same launcher.
   * `orphan` — the launcher works, but nothing claims it.
   */
  unknown_shortcuts: Array<{
    app_id: number;
    title: string;
    exe: string;
    launcher: string;
    launcher_exists: boolean;
    kind: "dead" | "duplicate" | "orphan";
  }>;
  previous_installs: Array<{
    name: string;
    path: string;
    games: Array<{
      app_id: number;
      title: string;
      rom_path: string;
      core_id: string;
      rom_exists: boolean;
    }>;
  }>;
}

export const auditLibrary = callable<[], AuditReport>("audit_library");

/**
 * The appid of a Steam shortcut already running this launcher, or 0.
 *
 * Read from Steam's shortcuts.vdf, which is the only place an appid and the
 * executable it runs are written down together — `appStore` can confirm an
 * appid exists but not say what it launches.
 */
export const shortcutForLauncher = callable<[exe: string], { app_id: number }>(
  "shortcut_for_launcher",
);

export interface ReceivedFile {
  name: string;
  path: string;
  size: number;
  at: number;
}

/** A file still arriving. `total` is the size its sender declared. */
export interface UploadInFlight {
  /** What cancelUpload is addressed by; two devices can send the same name. */
  id: number;
  name: string;
  received: number;
  total: number;
  /** Already asked to stop, but the handler has not let go yet. */
  cancelled: boolean;
}

export interface FileServerStatus {
  running: boolean;
  /** Contains the access token, so treat it as a secret while running. */
  url: string;
  /** Tokenless address for the code form — short enough to type on a keyboard. */
  short_url: string;
  /** Six digits that redirect to `url`. Empty when not running. */
  pin: string;
  /** True once too many wrong codes were tried; a restart mints a new one. */
  pin_locked: boolean;
  /** Uploads in flight. Stopping now would cut them off. */
  uploading: number;
  /** Those same uploads with their progress, oldest first. */
  uploads: UploadInFlight[];
  port: number;
  target_dir: string;
  received: ReceivedFile[];
  idle_seconds: number;
  idle_timeout: number;
  suggested_dir?: string;
}

export const fileServerStatus = callable<[], FileServerStatus>("file_server_status");
/** An empty `targetDir` means the default folder, resolved by the backend. */
export const startFileServer = callable<
  [targetDir: string],
  { ok: boolean; error?: string } & Partial<FileServerStatus>
>("start_file_server");
export const stopFileServer = callable<
  [],
  { ok: boolean } & Partial<FileServerStatus>
>("stop_file_server");

/**
 * Abandon a transfer in progress. `0` cancels every one of them.
 *
 * The half-written file is deleted with it: nothing can resume an upload, so
 * keeping it would only leave litter in the folder the user browses for ROMs.
 */
export const cancelUpload = callable<
  [uploadId: number],
  { ok: boolean; cancelled: number } & Partial<FileServerStatus>
>("cancel_upload");

/**
 * Invalidate every saved transfer link and issue a fresh one.
 *
 * All or nothing: the link is the credential, so there is nothing per-device to
 * revoke. Refused while a transfer is running, since taking the address away
 * mid-upload would cut off the device using it.
 */
export const resetTransferLink = callable<
  [],
  { ok: boolean; error?: string } & Partial<FileServerStatus>
>("reset_transfer_link");
export const adoptPreviousInstall = callable<
  [path: string],
  {
    ok: boolean;
    error?: string;
    adopted?: Array<{ app_id: number; title: string; exe: string; collection: string }>;
    skipped?: string[];
  }
>("adopt_previous_install");
export const forgetGames = callable<
  [appIds: number[]],
  {
    ok: boolean;
    removed: string[];
    /** With the collection each was filed into, so it can be emptied too. */
    games: Array<{ app_id: number; title: string; collection: string }>;
  }
>("forget_games");

/**
 * Delete an old install's registry so it stops being offered for adoption.
 *
 * Its launcher scripts are left alone: they are why the old shortcuts still work.
 */
export const discardPreviousInstall = callable<
  [path: string],
  { ok: boolean; error?: string; discarded?: number }
>("discard_previous_install");
export const deleteStrayLaunchers = callable<
  [paths: string[]],
  { ok: boolean; deleted: number }
>("delete_stray_launchers");

export const rebuildLaunchers = callable<
  [],
  { ok: boolean; error?: string; rebuilt?: number; skipped?: string[] }
>("rebuild_launchers");
