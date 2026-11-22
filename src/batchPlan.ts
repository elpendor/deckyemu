import type { ResolvedGame, RomProbe } from "./backend";
import { pendingPackage } from "./packageState";

/**
 * Where a file lands on the review, from what checking it found.
 *
 * Ready goes in as it is. Check goes in only when the doubt is about the name,
 * which the row shows; a duplicate or a warned-about dump waits to be ticked.
 * Other is a file that is not a game but belongs to one -- an update, a patch,
 * a save -- and has its own action. Can't is what nothing here can use.
 */
export type Bucket = "ready" | "check" | "other" | "cant";

/**
 * Something a game row needs done before it can be added. The row offers it as
 * a button, and **Add** does it first for a ticked row that still needs it.
 */
export type Step = "" | "unpack" | "package" | "emulator" | "core" | "retroarch";

/** What a non-game row does, and what its button says. */
export type OtherKind =
  | "definition" | "firmware" | "licence" | "key" | "content" | "patch" | "save" | "disc";

export interface Verdict {
  bucket: Bucket;
  /** One short line for the row; "" when there is nothing to say. */
  reason: string;
  /** Whether the row starts ticked. */
  include: boolean;
  step?: Step;
  other?: OtherKind;
}

const cant = (reason: string): Verdict => ({ bucket: "cant", reason, include: false });
const check = (reason: string, include: boolean, step: Step = ""): Verdict =>
  ({ bucket: "check", reason, include, step });
const other = (kind: OtherKind, reason: string): Verdict =>
  ({ bucket: "other", reason, include: false, other: kind });

/** What the probe alone says, before any lookup. `retroarch` is whether
 *  RetroArch is installed, `installable` how many cores could be. */
export function classifyProbe(
  probe: RomProbe,
  installable = 0,
  retroarch = true,
): Verdict | null {
  if (probe.save_backup) return other("save", "A save backup");
  if (probe.rom_patch) return other("patch", "A ROM hack");
  if (probe.game_content) return other("content", probe.game_content.label || "An update or DLC");

  const packaged = pendingPackage(probe);
  if (packaged) {
    if (!packaged.state.emulator_ready) {
      return check(`Installs ${packaged.state.emulator_name || "its emulator"}, then the game`, true, "emulator");
    }
    if (packaged.system === "vita" && packaged.state.licence === false) {
      // The wrong key installs gigabytes and then fails to decrypt, so a key
      // not named for this game is picked by a person, in the Fix dialog.
      return (packaged.state.licence_candidates ?? []).length
        ? check("Pick its licence key", false, "package")
        : check("Send its licence key too", false, "package");
    }
    const into = packaged.state.emulator_name ? ` into ${packaged.state.emulator_name}` : "";
    return check(`Installs${into} first${packaged.system === "vita" ? " · key found" : ""}`, true, "package");
  }
  if (probe.vita_release) return cant("A Vita release: send its .pkg instead");

  // Nothing can open it as it is, but it comes apart: an Xbox 360 zip, an .nsz.
  const mustUnpack = probe.can_unpack &&
    (probe.archived_content || probe.unpack_kind === "nsz" || !probe.suggested_core_id);
  if (mustUnpack) return check("Unpacks first", true, "unpack");

  if (!probe.suggested_core_id) {
    if (probe.unsupported_extension) return cant("Not a game file");
    if (installable > 0) {
      return retroarch
        ? check("Installs a core first", true, "core")
        : check("Needs RetroArch", false, "retroarch");
    }
    return cant(probe.what ? `Nothing runs ${probe.what} files` : "Nothing runs it");
  }
  return null;
}

/** The row's place once the lookup is in. `resolved` is null when it failed. */
export function classify(
  probe: RomProbe,
  resolved: ResolvedGame | null,
  installable = 0,
  retroarch = true,
): Verdict {
  const early = classifyProbe(probe, installable, retroarch);
  if (early) return early;
  if (probe.already_added) {
    return check(`Already in your library as ${probe.already_added.name || "a game"}`, false);
  }
  if (probe.unsupported_extension) return check("Usually a save or config file", false);
  const warning = probe.disc_warning || probe.dump_warning || probe.track_warning
    || probe.disc_folder_warning;
  if (warning) return check(firstSentence(warning), false);
  if (!resolved) return check("Lookup failed", true);
  if (resolved.title_source === "filename") return check("Not recognised", true);
  if (resolved.match_kind !== "exact" && resolved.art_game_name) {
    // The title usually comes from the same loose match, so naming it again
    // says nothing; say how it was found instead.
    const same = resolved.art_game_name.toLowerCase() === resolved.title.toLowerCase();
    return check(same ? "Close match" : `Artwork is for ${resolved.art_game_name}`, true);
  }
  return { bucket: "ready", reason: "", include: true };
}

/** A received file that is not a game, from what the transfer list knows. */
export function otherVerdict(kind: OtherKind, label = ""): Verdict {
  const reasons: Record<OtherKind, string> = {
    definition: "An emulator definition",
    firmware: "BIOS or firmware",
    licence: "A PS3 licence",
    key: "A Vita licence key, used when its .pkg installs",
    content: label || "An update or DLC",
    patch: "A ROM hack",
    save: "A save backup",
    disc: label || "A disc of a game you added",
  };
  return other(kind, reasons[kind]);
}

function firstSentence(text: string): string {
  const cut = text.search(/[.!?](\s|$)/);
  return cut < 0 ? text : text.slice(0, cut + 1);
}
