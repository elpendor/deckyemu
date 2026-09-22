import type { ReceivedFile } from "./backend";

/**
 * One row of the Received list, and everything that row speaks for.
 *
 * A CD rip arrives as a `.cue` and a dozen `.bin` files. Listed flat that is
 * thirteen rows of one game, each with its own **Add** — and Add on a `.bin`
 * makes a Steam entry out of raw sectors, which is the confusion worth removing
 * rather than the rows.
 *
 * So the tracks fold into the sheet that names them. Nothing is hidden: the
 * count above the list still counts files, so it still matches what was sent,
 * and the names are a button away. The backend decides what owns what — see
 * `romshelf.sheet_owners`, which resolves a `.bin` past its `.cue` to the
 * `.m3u` at the top when there is one, so a multi-disc set is also one row.
 */
export interface ReceivedGroup {
  /** The row itself: a playlist, or a file nothing here names. */
  file: ReceivedFile;
  /** What it owns, newest-first as the backend listed them. Often empty. */
  tracks: ReceivedFile[];
  /** The set on disk — what the row reports and what discarding it costs. */
  size: number;
}

/** The folder part of a path, "" for a bare name. */
function folderOf(path: string): string {
  const cut = path.lastIndexOf("/");
  return cut < 0 ? "" : path.slice(0, cut);
}

/**
 * The received list folded into one row per game, in the order it came in.
 *
 * Owners are matched within a folder. `part_of` is a bare filename because that
 * is what a playlist may contain, and the received list is not guaranteed to be
 * one directory — it follows the running server, so a firmware send saves
 * somewhere else. Two `Game.bin` files under two folders must not collapse onto
 * whichever `Game.cue` came first.
 */
export function groupReceived(files: ReceivedFile[]): ReceivedGroup[] {
  // An owner that is not on the list cannot fold anything into itself, and the
  // file naming it must keep its row rather than vanish into a group that is
  // not there. The backend only ever names a sheet it listed, so this is the
  // frontend refusing to depend on that -- the cost of being wrong is a file
  // the user can no longer reach.
  const here = new Set(files.map((file) => `${folderOf(file.path)}/${file.name}`));
  const ownerOf = (file: ReceivedFile) => {
    if (!file.part_of) return "";
    const key = `${folderOf(file.path)}/${file.part_of}`;
    return here.has(key) ? key : "";
  };

  const owned = new Map<string, ReceivedFile[]>();
  for (const file of files) {
    const key = ownerOf(file);
    if (!key) continue;
    const list = owned.get(key);
    if (list) list.push(file);
    else owned.set(key, [file]);
  }

  return files
    .filter((file) => !ownerOf(file))
    .map((file) => {
      const tracks = owned.get(`${folderOf(file.path)}/${file.name}`) ?? [];
      return {
        file,
        tracks,
        size: tracks.reduce((total, one) => total + one.size, file.size),
      };
    });
}

/**
 * What to call the things a playlist owns, singular.
 *
 * A `.cue` names the tracks of one disc and "track" is what every ripper calls
 * them. An `.m3u` names discs, and what hangs off it here is their sheets *and*
 * their tracks both, so the only word true of all of them is "file".
 */
export function ownedNoun(playlist: string): "track" | "file" {
  return playlist.toLowerCase().endsWith(".m3u") ? "file" : "track";
}

/** `12 tracks`, `1 track`, `26 files` — the subtitle's tail. */
export function ownedCount(playlist: string, count: number): string {
  const noun = ownedNoun(playlist);
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}
