import { type AddedGame } from "./backend";

/**
 * What system a game runs on, for display.
 *
 * `platform` is the short label ("Switch", "SNES"). `system` is the libretro
 * database name, which is empty for emulators libretro has no system for -- and
 * falling through to `core_id` showed the internal namespaced id ("emu:xemu"),
 * which is never meant to be seen.
 */
export function systemLabel(game: AddedGame): string {
  if (game.platform) return game.platform;
  if (game.system) return game.system.split(" - ").pop() ?? game.system;
  return game.core_id.replace(/^emu:/, "") || "Unknown system";
}
