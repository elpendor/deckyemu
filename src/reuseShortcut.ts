import { shortcutForLauncher } from "./backend";
import {
  createShortcut,
  pinGamepadLayout,
  repointShortcut,
  renameShortcut,
  shortcutExists,
} from "./steam";
import { logError } from "./logError";

/**
 * Make a shortcut for a launcher, or take back over the one already there.
 *
 * Adding a game creates a Steam shortcut and records its appid. Nothing checked
 * whether Steam already had one for the same launcher, so any loss of the
 * registry -- a reset, a restored backup, a crash between creating the shortcut
 * and recording it -- meant re-adding the game produced a second entry beside
 * the first, both pointing at the same script.
 *
 * The launcher path is the identity: it is derived from the title and the ROM
 * path, so the same game added the same way lands on the same script. Steam's
 * shortcuts.vdf is the only place the appid and the executable are written down
 * together, so the lookup goes through the backend -- `appStore` can answer
 * "does appid N exist" but cannot say what any shortcut runs.
 *
 * Deliberately not a name match. Two shortcuts called "Super Mario 3D World"
 * could be one of ours and one real Steam entry, and taking over the wrong one
 * would rewrite somebody's actual game.
 *
 * Kept out of `steam.ts` because that file must stay free of backend imports:
 * it is exercised by tests that run under Node, where `@decky/api` will not
 * load.
 */
export async function createOrReuseShortcut(args: {
  title: string;
  exe: string;
  startDir: string;
  launchOptions: string;
  /** A Steam Input layout the emulator needs; "" leaves Steam's choice alone. */
  layout?: string;
}): Promise<{ appId: number; reused: boolean }> {
  let existing = 0;
  try {
    const found = await shortcutForLauncher(args.exe);
    existing = found.app_id ?? 0;
  } catch (error) {
    // A failed lookup must not stop a game being added: the cost of missing a
    // duplicate is a second entry the cleanup screen can remove, and the cost
    // of refusing here is that the game cannot be added at all.
    logError("could not check for an existing shortcut", error);
  }

  // Steam is the authority on whether it still has it. shortcuts.vdf is
  // written on Steam's own schedule, so it can name an appid that has since
  // been deleted -- and reusing a dead one would return an id nothing renders.
  if (existing > 0 && shortcutExists(existing)) {
    // The name may have changed since, and the launcher may have been rewritten
    // to a different path for the same game, so both are re-applied rather than
    // assumed. This is the same repair the audit's adopt path performs.
    renameShortcut(existing, args.title);
    repointShortcut(existing, args.exe);
    // The name is the key Steam files a controller layout under, so a rename
    // moves the shortcut onto whatever layout that title already attracts --
    // the same guess a fresh shortcut gets, and worth the same repair. Not
    // awaited, for the reason `createShortcut` gives.
    void pinGamepadLayout(existing, 8, args.layout ?? "");
    return { appId: existing, reused: true };
  }

  return { appId: await createShortcut(args), reused: false };
}
