/**
 * Whether a ROM's filename is the game's name, or just how it boots.
 *
 * Everything installed from a package -- PS3, PS4 and Vita -- launches an
 * `eboot.bin`. PS3 games sit at `USRDIR/EBOOT.BIN`, a Vita title at
 * `ux0/app/PCSA00011/eboot.bin`, and the folder above it is a title id rather
 * than a name. So the file says nothing about which game it is, and looking one
 * up by filename searches for "Eboot" -- for every such game, identically.
 *
 * The backend already knows this on the way *in*: `resolve_game` takes a
 * `title` override precisely so a game added from a package searches for what
 * its PARAM.SFO said. What was missing is that the editor never passed it, so
 * re-running the lookup on an added game went back to searching for "Eboot".
 *
 * A list of exact stems rather than a guess at what looks like a name. A ROM
 * genuinely called `Golf.nes` is a name; the point is not to be clever about
 * which words are titles, only to know the handful that are never titles.
 * Anything not listed is taken at face value.
 */
const NOT_A_TITLE = new Set(["eboot"]);

/** The filename without its directory or extension, lowercased. */
function stem(romPath: string): string {
  const base = romPath.slice(romPath.lastIndexOf("/") + 1);
  const dot = base.lastIndexOf(".");
  return (dot > 0 ? base.slice(0, dot) : base).toLowerCase();
}

/**
 * True when searching by the filename could plausibly find the game.
 *
 * The caller uses this twice over: to decide whether to hand the lookup a title
 * instead, and to label the button honestly. "Look up by filename" on a game
 * whose filename is `eboot.bin` describes something that cannot work.
 */
export function filenameNamesTheGame(romPath: string): boolean {
  const name = stem(romPath);
  return name !== "" && !NOT_A_TITLE.has(name);
}
