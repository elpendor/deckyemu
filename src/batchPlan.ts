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
  | "definition" | "firmware" | "key" | "content" | "patch" | "save" | "disc";

export interface Verdict {
  bucket: Bucket;
  /** One short line for the row; "" when there is nothing to say. */
  reason: string;
  /** Whether the row starts ticked. */
  include: boolean;
  step?: Step;
  other?: OtherKind;
  /** Not addable until something only the user can do is done; it cannot be
   *  ticked meanwhile, and `reason` says what. */
  blocked?: boolean;
  /** Nothing claims the file, so it waits for an emulator picked by hand. */
  pick?: boolean;
}

/** The verdict once an emulator is picked for a file nothing claimed. */
export const PICKED: Verdict = { bucket: "check", reason: "Chosen by you", include: true };

/** `verdict`, unless it waits for a pick and `coreId` is that pick. */
export const withPick = (verdict: Verdict, coreId: string): Verdict =>
  verdict.pick && coreId ? PICKED : verdict;

const cant = (reason: string): Verdict => ({ bucket: "cant", reason, include: false });
const check = (reason: string, include: boolean, step: Step = ""): Verdict =>
  ({ bucket: "check", reason, include, step });
const blocked = (reason: string, step: Step): Verdict =>
  ({ bucket: "check", reason, include: false, step, blocked: true });
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
    // A Vita key is matched to its package by what it licenses, so a missing
    // one is the only thing to say -- and it is said before any install.
    if (packaged.system === "vita" && packaged.state.licence === false) {
      return (packaged.state.licence_candidates ?? []).length
        ? blocked("The key here is for another game", "package")
        : blocked("Needs its licence key", "package");
    }
    // A PS3 package says whether it is licence-free; one that is not cannot
    // start without its .rap.
    if (packaged.system === "ps3" && packaged.state.licence_needed === true
      && packaged.state.licence_state === "") {
      return blocked("Needs its licence key", "package");
    }
    const name = packaged.state.emulator_name || "its emulator";
    const key = packaged.system === "vita" ? " · key matched" : "";
    if (!packaged.state.emulator_ready) {
      // Its firmware is Sony's to download, so it comes with the emulator.
      const what = packaged.state.needs_firmware ? `${name} and its firmware install` : `${name} installs`;
      return check(`${what} on Add, then the game${key}`, true, "emulator");
    }
    return check(`Installs into ${name} on Add${key}`, true, "package");
  }
  if (probe.vita_release) return cant("A Vita release: send its .pkg instead");

  // Nothing can open it as it is, but it comes apart: an Xbox 360 zip, an .nsz.
  const mustUnpack = probe.can_unpack &&
    (probe.archived_content || probe.unpack_kind === "nsz" || probe.zipped_disc || !probe.suggested_core_id);
  // What it unpacks to is known, and with nothing installed to run that the
  // unpack would only end in a file nobody can play.
  const into = unpacksTo(probe);
  if (mustUnpack && into
    && !(probe.all_cores ?? []).some((core) => core.extensions.includes(into.extension))) {
    return blocked(`Needs ${into.emulator}: add one from the Emulators tab`, "unpack");
  }
  if (mustUnpack) return check("Unpacks first", true, "unpack");

  if (!probe.suggested_core_id) {
    // Forcing something installed is sometimes right, so the pencil offers it.
    const pickable = (probe.all_cores ?? []).length > 0;
    const pick = (reason: string): Verdict => ({ ...blocked(reason, ""), pick: true });
    if (probe.unsupported_extension) {
      return pickable ? pick("Usually a save or config file: the pencil picks an emulator")
        : cant("Not a game file");
    }
    if (installable > 0) {
      return retroarch
        ? check("Installs a core first", true, "core")
        : blocked("Needs RetroArch", "retroarch");
    }
    const what = probe.what ? `${probe.what} files` : "it";
    return pickable ? pick(`Nothing claims ${what}: the pencil picks an emulator`)
      : cant(`Nothing runs ${what}`);
  }
  return null;
}

/**
 * What a file that must unpack first becomes, when that is known before
 * unpacking: an .nsz is an .nsp, and a zip holding an Xbox 360 package is that
 * package. The system and emulator are for the row and its block.
 */
export function unpacksTo(probe: RomProbe): { extension: string; system: string; emulator: string } | null {
  if (!probe.can_unpack) return null;
  if (probe.unpack_kind === "nsz") {
    return { extension: "nsp", system: "Nintendo - Switch", emulator: "a Switch emulator" };
  }
  if (probe.archived_content === "stfs" || probe.archived_content === "xex") {
    return { extension: probe.archived_content, system: "Microsoft - Xbox 360", emulator: "an Xbox 360 emulator" };
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
    key: "A licence key, used when its game is added",
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
