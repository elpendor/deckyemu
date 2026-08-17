import { callable } from "@decky/api";

/**
 * Signing in to somebody else's service: RetroAchievements and SteamGridDB.
 *
 * Mirrors `plugin_accounts.py`, which groups them for the reason that shows up
 * here too -- both are a credential this plugin holds on the user's behalf, both
 * have to be obtainable without typing on the on-screen keyboard, and both would
 * otherwise be a stray pair of endpoints in a file about something else.
 *
 * Neither password nor key is ever handed back to the frontend. RetroAchievements
 * returns a username; the SteamGridDB endpoints return whether a key was found
 * and where from.
 */

/** Who is signed in to RetroAchievements, and whether RetroArch has a login to adopt. */
export interface CheevosStatus {
  signed_in: boolean;
  username: string;
  enabled: boolean;
  hardcore: boolean;
  can_adopt: boolean;
  retroarch_username: string;
}

export const cheevosStatus = callable<[], CheevosStatus>("cheevos_status");

/** The password is used for this one call and never stored; only the token is. */
export const cheevosLogin = callable<
  [string, string],
  { ok: boolean; error?: string; username?: string }
>("cheevos_login");

/**
 * Take the Connect token already in retroarch.cfg. A token there is as good as
 * one of ours, and adopting it is the only route into RetroAchievements that
 * needs nothing typed.
 */
export const cheevosAdopt = callable<[], { ok: boolean; error?: string; username?: string }>(
  "cheevos_adopt",
);

export const cheevosSignOut = callable<[], { ok: boolean }>("cheevos_sign_out");

export const validateSgdbKey = callable<
  [apiKey: string],
  { ok: boolean; error?: string }
>("validate_sgdb_key");

/** `source` names the plugin the key was found in, for a prompt that can say so. */
export const findExistingSgdbKey = callable<[], { found: boolean; source: string }>(
  "find_existing_sgdb_key",
);
export const importExistingSgdbKey = callable<
  [],
  { ok: boolean; error?: string; how?: string }
>("import_existing_sgdb_key");
