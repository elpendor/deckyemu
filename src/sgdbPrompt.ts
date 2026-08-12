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

/*
 * Module scope, deliberately, and for the same reason the ROM draft lives
 * outside React: following the prompt closes the Quick Access panel, and the
 * panel's component goes with it. Anything remembered in a `useRef` is gone by
 * the time the answer matters -- the remount sees "no idea -> key present"
 * rather than "no key -> key present" and concludes nothing happened.
 */
let lastKeyState: boolean | null = null;

/**
 * Whether a key has appeared since this was last asked. Asking consumes it.
 *
 * A transition rather than a state, because "art on screen is not from
 * SteamGridDB while a key exists" is also true of every game SteamGridDB has
 * never heard of -- acting on that would look the game up again every time the
 * panel opened, forever.
 *
 * Only call this when the answer would be acted on. It is a one-shot: the
 * caller is expected to look the artwork up again, and asking twice about the
 * same key would look it up twice.
 */
export function sgdbKeyJustAppeared(settings: SgdbPromptSettings | null | undefined): boolean {
  if (!settings) return false;
  const previous = lastKeyState;
  lastKeyState = settings.sgdb_api_key_set;
  // `previous === null` is the first look of the session, which establishes the
  // state rather than reporting a change: a key that was already there before
  // the plugin loaded is not news.
  return previous === false && settings.sgdb_api_key_set;
}
