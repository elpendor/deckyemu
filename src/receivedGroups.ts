import type { ReceivedFile } from "./backend";
import type { OtherKind } from "./batchPlan";

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
  /**
   * For a game on several discs: every disc's sheet, in disc order, the first
   * being `file`. The row is named for the game and speaks for all of them.
   */
  discs?: ReceivedFile[];
  /** The game's name without its disc number, for a set. */
  title?: string;
  /** Its update, DLC or licence key, sent with it: they go in with it. */
  brought?: ReceivedFile[];
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

  const rows: ReceivedGroup[] = files
    .filter((file) => !ownerOf(file))
    .map((file) => {
      const tracks = owned.get(`${folderOf(file.path)}/${file.name}`) ?? [];
      return {
        file,
        tracks,
        size: tracks.reduce((total, one) => total + one.size, file.size),
      };
    });
  return foldBrought(foldDiscSets(rows));
}

/**
 * A game's update, DLC or key into the game's row, as the review shows it:
 * one row per game, and what goes in with it counted there.
 */
function foldBrought(rows: ReceivedGroup[]): ReceivedGroup[] {
  const owner = new Map<string, ReceivedGroup>();
  for (const row of rows) {
    for (const name of row.file.brings ?? []) owner.set(`${folderOf(row.file.path)}/${name}`, row);
  }
  const folded = new Set<ReceivedGroup>();
  for (const row of rows) {
    const game = owner.get(`${folderOf(row.file.path)}/${row.file.name}`);
    if (!game || game === row) continue;
    game.brought = [...(game.brought ?? []), row.file];
    game.size += row.size;
    folded.add(row);
  }
  return rows.filter((row) => !folded.has(row));
}

/** "+ 1 update · 1 DLC · key" for a row that brings something, or "". */
export function broughtSummary(brought: ReceivedFile[] = []): string {
  const updates = brought.filter((file) => /^update/i.test(file.game_content?.label ?? "")).length;
  const dlc = brought.filter((file) => file.game_content && !/^update/i.test(file.game_content.label ?? "")).length;
  const keys = brought.filter((file) => file.licence_key || file.name.toLowerCase().endsWith(".rap")).length;
  const parts = [
    updates ? `${updates} update${updates === 1 ? "" : "s"}` : "",
    dlc ? `${dlc} DLC` : "",
    keys ? "key" : "",
  ].filter(Boolean);
  return parts.length ? `+ ${parts.join(" · ")}` : "";
}

/**
 * The discs of one game as one row, where the first disc to arrive stood.
 * Only a game with two or more discs here, and never a disc of a game already
 * added: that row joins its game instead.
 */
function foldDiscSets(rows: ReceivedGroup[]): ReceivedGroup[] {
  const keyOf = ({ file }: ReceivedGroup) =>
    file.disc_set && !file.disc_for ? `${folderOf(file.path)}/${file.disc_set}` : "";
  const sets = new Map<string, ReceivedGroup[]>();
  for (const row of rows) {
    const key = keyOf(row);
    if (key) sets.set(key, [...(sets.get(key) ?? []), row]);
  }
  const out: ReceivedGroup[] = [];
  for (const row of rows) {
    const set = sets.get(keyOf(row));
    if (!set || set.length < 2) {
      out.push(row);
      continue;
    }
    if (set[0] !== row) continue;
    const ordered = [...set].sort((a, b) => (a.file.disc_number ?? 0) - (b.file.disc_number ?? 0));
    out.push({
      file: ordered[0].file,
      // Everything the set holds besides the first sheet, disc by disc.
      tracks: ordered.flatMap((one, index) => (index ? [one.file, ...one.tracks] : one.tracks)),
      size: ordered.reduce((total, one) => total + one.size, 0),
      discs: ordered.map((one) => one.file),
      title: ordered[0].file.disc_title || ordered[0].file.name,
    });
  }
  return out;
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

const DEFINITION_SUFFIX = ".deckyemu.json";
const PATCH_SUFFIXES = [".ips", ".bps", ".ups"];

/**
 * The rows whose button is plain **Add**: what **Add all** takes.
 *
 * Mirrors the order of the button chain in `TransferModal`'s received list;
 * a row that chain gives any other button is not a game to add.
 */
export function addableGroups(
  groups: ReceivedGroup[],
  purpose: string,
  isFirmware: (name: string) => boolean,
): ReceivedGroup[] {
  if (purpose === "firmware" || purpose === "backup") return [];
  return groups.filter(({ file }) => {
    const name = file.name.toLowerCase();
    return !(
      name.endsWith(DEFINITION_SUFFIX) ||
      isFirmware(file.name) ||
      name.endsWith(".rap") ||
      file.licence_key ||
      file.game_content ||
      PATCH_SUFFIXES.some((one) => name.endsWith(one)) ||
      file.disc_for
    );
  });
}

/** A received row as the review takes it: a game, or what else it is. */
export interface BatchInput {
  path: string;
  name: string;
  /** Not a game: what it is, from what the transfer list knows of it. */
  other?: OtherKind;
  file?: ReceivedFile;
}

/**
 * Every row the review takes, games and the files that belong to games alike.
 * The same decision the button chain in `TransferModal` makes, kept as data:
 * a row that chain gives Import, Install or Add to game is not a game to add,
 * so it goes in as what it is and the review offers that same action.
 */
export function batchInputs(
  groups: ReceivedGroup[],
  purpose: string,
  isFirmware: (name: string) => boolean,
): BatchInput[] {
  if (purpose === "firmware") return [];
  return groups.flatMap(({ file, discs, brought }): BatchInput | BatchInput[] => {
    // What a game brings goes in as itself too; the review pairs it again.
    if (brought?.length) {
      return batchInputs([{ file, tracks: [], size: 0, discs }, ...brought.map((one) => ({ file: one, tracks: [], size: 0 }))],
        purpose, isFirmware);
    }
    // Each disc of a set goes in as itself; the review joins them again.
    if (discs && purpose !== "backup") return discs.map((disc) => ({ path: disc.path, name: disc.name, file: disc }));
    const name = file.name.toLowerCase();
    const as = (other?: OtherKind): BatchInput =>
      ({ path: file.path, name: file.name, other, file });
    if (purpose === "backup") return as("save");
    if (name.endsWith(DEFINITION_SUFFIX)) return as("definition");
    if (isFirmware(file.name)) return as("firmware");
    // A .rap or a Vita key: both go in with their game, and nothing else.
    if (file.licence_key || name.endsWith(".rap")) return as("key");
    if (file.game_content) return as("content");
    if (PATCH_SUFFIXES.some((one) => name.endsWith(one))) return as("patch");
    if (file.disc_for) return as("disc");
    return as();
  });
}
