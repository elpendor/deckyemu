/**
 * The nudge towards a SteamGridDB key, and the one rule for when it appears.
 *
 * What a key actually buys is not sharpness. libretro's thumbnails are scans of
 * the physical box and there is only ever one of them, so a game added without a
 * key gets a cover and nothing else: `main.py` hands the art layer
 * `{"capsule": ...}` alone. SteamGridDB has four slots (see `SLOT_URLS` in
 * `sgdb.py`) -- capsule, header, hero and logo -- so with a key the game's Steam
 * page is finished rather than a cover on top of Steam's defaults.
 *
 * That is the difference worth a row in the panel, and it is what the wording
 * says. Anything about quality would be a claim this cannot support: a box scan
 * of a game nobody has uploaded to SteamGridDB is the better picture.
 *
 * Kept apart from the panel so the condition and the copy are one decision in
 * one place rather than a condition inlined in every surface that shows it.
 */

/** Only the part of `PluginSettings` this needs, so tests need not build one. */
export interface SgdbPromptSettings {
  sgdb_api_key_set: boolean;
}

export const SGDB_PROMPT = {
  label: "Only the cover will have artwork",
  description:
    "libretro has box scans and nothing else, so the game's Steam page keeps its " +
    "default banner and gets no logo. A free SteamGridDB key fills those in too.",
  action: "Set up SteamGridDB",
} as const;

/**
 * Whether to offer the prompt.
 *
 * Keyed on the key alone. The artwork *source* setting is not consulted on
 * purpose: without a key, SteamGridDB cannot be reached whatever it is set to,
 * so the key is the whole question. Somebody who has a key and has chosen
 * libretro anyway has answered this already, and asking again would be nagging
 * about a decision they made on the settings page this row points at.
 *
 * Null while settings are still loading -- silent then, because a prompt that
 * appears and then vanishes a moment later reads as a glitch.
 */
export function shouldOfferSgdb(settings: SgdbPromptSettings | null | undefined): boolean {
  if (!settings) return false;
  return !settings.sgdb_api_key_set;
}
