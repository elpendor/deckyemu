/**
 * Adding games: check every file, review, add. One file or fifty, from the
 * transfer list or the file browser, all come through here.
 *
 * Held at module scope because Steam unmounts what is behind a modal, and a
 * batch of fifty, a package install or an emulator install takes minutes. Each
 * game goes in through `addGameToSteam`; whatever a file needs first -- an
 * unpack, a package install, a core or an emulator -- is a step on its row.
 */

import {
  clearStashedArt,
  fetchFirmware,
  installFirmware,
  type AppliedArt,
  getStatus,
  installCore,
  installEmulator,
  installPs3Package,
  installPs4Package,
  installVitaPackage,
  type InstallableCore,
  joinDiscToGame,
  listInstalledPs3Games,
  listInstalledPs4Games,
  listInstalledVitaGames,
  missingFirmware,
  probeRom,
  ps3CoreId,
  ps4CoreId,
  type ReceivedFile,
  resolveGameStashed,
  suggestCoresForExtension,
  takeStashedArt,
  unpackTransferredFile,
  vitaCoreId,
  type ResolvedGame,
  type RomProbe,
} from "./backend";
import { addGameToSteam } from "./addToSteam";
import { classify, classifyProbe, otherVerdict, unpacksTo, type OtherKind, type Verdict } from "./batchPlan";
import { chooseSystem } from "./corePicker";
import { discsMustSplit as mustSplit } from "./discSet";
import { addEventListener, removeEventListener } from "./host";
import { logError } from "./logError";
import { pendingPackage, type PackageSystem } from "./packageState";
import { repointShortcut } from "./steam";

export type DiscMode = "one" | "each";

/** One Steam entry a row made. */
interface Added {
  appId: number;
  /** Where its ROM went, "" when nothing was moved (an installed package). */
  filedPath: string;
}

export interface BatchRow {
  path: string;
  name: string;
  probe: RomProbe | null;
  coreId: string;
  systemId: string;
  title: string;
  /** Vita3K starts a title id rather than a file. */
  titleId: string;
  resolved: (ResolvedGame & { art_key: string }) | null;
  /** The discs of this game; fewer than two is a single file. */
  discs: string[];
  /** Whether `discs` go in as one game or each on its own. */
  discMode: DiscMode;
  verdict: Verdict;
  include: boolean;
  /** Looking up, or running a step. */
  busy: boolean;
  /** What a running step is doing, and how far; -1 when it cannot say. */
  stepStatus: string;
  stepPercent: number;
  outcome: "" | "added" | "failed" | "done";
  error: string;
  added: Added[];
  /** Named or matched by hand, which a later lookup must not undo. */
  fixed: boolean;
  /** The system was picked by hand, so a core change keeps it where it can. */
  systemPicked: boolean;
  /** Emulator picked for this row alone; the file-type picker leaves it. */
  corePicked: boolean;
  /** Cores that could run it, when none installed can; which one to install. */
  installable: InstallableCore[];
  installableId: string;
  /** What the chosen emulator is missing before a game boots. */
  needs: Needs;
  /** What the transfer list knows of a file that is not a game. */
  file: ReceivedFile | null;
}

/**
 * What an emulator still needs before its games boot, sorted by who supplies
 * it: what DeckyEmu downloads itself (Sony's firmware), and what only the
 * user can (a BIOS or keys copied off their own hardware).
 */
export interface Needs {
  emulator: string;
  download: { entryId: string; name: string }[];
  /** What only the user can send, with what each is ("PS1 US BIOS"). */
  /** `blocks`: no game starts without it, or only these file types' games. */
  send: { name: string; label: string; blocks?: boolean | string[] }[];
}

export const NO_NEEDS: Needs = { emulator: "", download: [], send: [] };

export type BatchPhase = "idle" | "checking" | "review" | "adding" | "done";

export interface Batch {
  phase: BatchPhase;
  rows: BatchRow[];
  /** Files checked, or games added, so far, against `total`. */
  done: number;
  total: number;
  /** The game being added right now. */
  current: string;
}

/** A file to check, and what is already known about it. */
export interface BatchFile {
  path: string;
  name: string;
  /** Not a game: see `batchInputs`. */
  other?: OtherKind;
  file?: ReceivedFile;
  /** Add this disc alone: the question was already put and answered no. */
  single?: boolean;
  /** A game already installed in RPCS3, shadPS4 or Vita3K, by title id. */
  packaged?: { system: PackageSystem; titleId: string };
}

const EMPTY: Batch = { phase: "idle", rows: [], done: 0, total: 0, current: "" };

let batch: Batch = EMPTY;
let generation = 0;
const listeners = new Set<(next: Batch) => void>();
/** Whether RetroArch is installed, asked once per batch. */
let retroarchFound = true;

export const getBatch = (): Batch => batch;

export function subscribeBatch(listener: (next: Batch) => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function update(patch: Partial<Batch>): void {
  batch = { ...batch, ...patch };
  for (const listener of listeners) listener(batch);
}

function updateRow(path: string, patch: Partial<BatchRow>): void {
  update({ rows: batch.rows.map((row) => (row.path === path ? unblock({ ...row, ...patch }) : row)) });
}

/** A blocked game stays unticked whatever else changes on its row. */
function unblock(row: BatchRow): BatchRow {
  return row.verdict.blocked && row.include ? { ...row, include: false } : row;
}

const rowAt = (path: string) => batch.rows.find((one) => one.path === path);
const folderOf = (path: string) => path.slice(0, path.lastIndexOf("/"));

/** How many files are checked at once: each is a probe and a few downloads. */
const PARALLEL = 3;

function newRow(file: BatchFile): BatchRow {
  return {
    path: file.path,
    name: file.name,
    probe: null,
    coreId: "",
    systemId: "",
    title: file.name,
    titleId: "",
    resolved: null,
    discs: [],
    discMode: "one",
    verdict: { bucket: "check", reason: "", include: false },
    include: false,
    busy: false,
    stepStatus: "",
    stepPercent: -1,
    outcome: "",
    error: "",
    added: [],
    fixed: false,
    systemPicked: false,
    corePicked: false,
    installable: [],
    installableId: "",
    needs: NO_NEEDS,
    file: file.file ?? null,
  };
}

/** Whether this row's discs must go in one entry each; see `discsMustSplit`. */
export const discsMustSplit = (row: BatchRow): boolean =>
  mustSplit(row.probe, row.coreId, row.discs);

// --- checking ---------------------------------------------------------------

/** The verdict for a game whose probe is gone: an installed package's eboot. */
function verdictWithoutProbe(resolved: ResolvedGame | null): Verdict {
  if (!resolved) return { bucket: "check", reason: "Lookup failed", include: true };
  return { bucket: "ready", reason: "", include: true };
}

async function lookUp(
  row: BatchRow, coreId: string, systemId: string, title = "",
): Promise<Partial<BatchRow>> {
  try {
    const resolved = await resolveGameStashed(row.path, coreId, title, systemId);
    return {
      resolved,
      title: resolved.title || title || row.title,
      verdict: row.probe ? classify(row.probe, resolved) : verdictWithoutProbe(resolved),
    };
  } catch (error) {
    logError("batch lookup failed", error);
    return { resolved: null, verdict: row.probe ? classify(row.probe, null) : verdictWithoutProbe(null) };
  }
}

/** What the chosen emulator is missing, per core, for the batch's life. */
const needsCache = new Map<string, Promise<Needs>>();
function needsFor(coreId: string): Promise<Needs> {
  if (!coreId) return Promise.resolve(NO_NEEDS);
  let known = needsCache.get(coreId);
  if (!known) {
    known = missingFirmware(coreId)
      .then((result): Needs => {
        const missing = result.missing ?? [];
        return {
          emulator: result.emulator ?? "Its emulator",
          download: missing.filter((item) => item.fetchable && item.entry_id)
            .map((item) => ({ entryId: item.entry_id!, name: item.name })),
          send: missing.filter((item) => !item.fetchable)
            .map((item) => ({
              name: posixBase(item.name), label: item.label ?? "", blocks: item.blocks ?? false,
            })),
        };
      })
      .catch(() => NO_NEEDS);
    needsCache.set(coreId, known);
  }
  return known;
}

/** `system/scph5501.bin` -> `scph5501.bin`. */
function posixBase(path: string): string {
  return path.slice(path.lastIndexOf("/") + 1);
}

const REGIONS: [RegExp, RegExp][] = [
  [/\((?:[^)]*\b)?(?:USA|US)\b/i, /\b(?:US|USA|NTSC-U|America)\b/i],
  [/\((?:[^)]*\b)?(?:Europe|EU|PAL)\b/i, /\b(?:EU|Europe|PAL)\b/i],
  [/\((?:[^)]*\b)?(?:Japan|JP)\b/i, /\b(?:JP|Japan|NTSC-J)\b/i],
];

/**
 * What this game asks to be sent. A BIOS set kept one per region names only
 * the game's own, from its filename tag: a USA disc wants the US BIOS, and
 * listing all three reads as three things missing.
 */
export function sendFor(row: { name: string; needs: Needs }): string[] {
  // What blocks the row is its reason already, not a recommendation.
  const send = row.needs.send.filter((item) => !blocksGame(item, row.name));
  for (const [game, file] of REGIONS) {
    if (!game.test(row.name)) continue;
    const own = send.filter((item) => file.test(item.label));
    if (own.length) return own.map((item) => item.name);
  }
  return send.map((item) => item.name);
}

/**
 * Updates and DLC whose game is in this batch, by file name, to that game's
 * title. Add installs them straight after the game; its row counts them.
 */
export function contentWithGames(rows: BatchRow[]): Map<string, string> {
  const owners = new Map<string, string>();
  for (const row of rows) {
    for (const one of row.probe?.content_waiting ?? []) owners.set(one.name, row.title);
  }
  return owners;
}

/** "+ 1 update · 2 DLC" for a game sent with its content, or "". */
export function contentSummary(row: BatchRow): string {
  const waiting = row.probe?.content_waiting ?? [];
  const updates = waiting.filter((one) => one.label.startsWith("Update")).length;
  const dlc = waiting.length - updates;
  const parts = [
    updates ? `${updates} update${updates === 1 ? "" : "s"}` : "",
    dlc ? `${dlc} DLC` : "",
  ].filter(Boolean);
  return parts.length ? `+ ${parts.join(" · ")}` : "";
}

/** Whether this missing file stops the game in `path` from starting. */
function blocksGame(item: Needs["send"][number], path: string): boolean {
  if (Array.isArray(item.blocks)) {
    const extension = path.slice(path.lastIndexOf(".") + 1).toLowerCase();
    return item.blocks.includes(extension);
  }
  return Boolean(item.blocks);
}

/** A row that cannot start without a file only the user can send. */
function waitingFor(needs: Needs, verdict: Verdict, path: string): Verdict {
  const missing = needs.send.filter((item) => blocksGame(item, path)).map((item) => item.name);
  if (!missing.length) return verdict;
  return {
    bucket: "check", include: false, blocked: true, step: verdict.step,
    reason: `Needs ${missing.join(", ")}: send it from the transfer page`,
  };
}

/** Firmware already fetched in this batch, so ten games ask for it once. */
const fetched = new Set<string>();

/** Download what DeckyEmu may fetch itself, before the game needing it. */
async function fetchNeeded(row: BatchRow): Promise<string[]> {
  const notes: string[] = [];
  for (const item of row.needs.download) {
    const key = `${item.entryId}/${item.name}`;
    if (fetched.has(key)) continue;
    // On the step line, as a package's install is; the bar keeps the game.
    updateRow(row.path, { busy: true, stepStatus: `Getting ${row.needs.emulator}'s firmware`, stepPercent: -1 });
    try {
      const result = await fetchFirmware(item.entryId, item.name);
      if (!result.ok) {
        notes.push(`${item.name} did not download: ${result.error ?? "no reason given"}`);
        continue;
      }
      // Downloaded is not installed: Vita3K imports its firmware itself, and
      // a game added before that boots to nothing.
      const installed = await installFirmware(item.entryId, item.name);
      if (installed.ok) fetched.add(key);
      else notes.push(`${item.name} downloaded but did not install: ${installed.error ?? "no reason given"}`);
    } catch (error) {
      logError("firmware download failed", error);
      notes.push(`${item.name} did not download.`);
    }
  }
  updateRow(row.path, { busy: false, stepStatus: "" });
  needsCache.clear();
  return notes;
}

const CONSOLES = {
  ps3: { games: listInstalledPs3Games, core: ps3CoreId, name: "RPCS3" },
  ps4: { games: listInstalledPs4Games, core: ps4CoreId, name: "shadPS4" },
  vita: { games: listInstalledVitaGames, core: vitaCoreId, name: "Vita3K" },
};

/**
 * An installed PS3, PS4 or Vita game as a row: its eboot, its title id, and
 * the name in its own param.sfo, so SteamGridDB is asked about the game rather
 * than a product code.
 */
async function packagedGame(
  row: BatchRow, system: PackageSystem, titleId: string,
): Promise<Partial<BatchRow>> {
  const { games: list, core, name } = CONSOLES[system];
  const [games, coreAnswer] = await Promise.all([list(), core()]);
  const game = games.games.find((one) => one.title_id === titleId);
  if (!game || !coreAnswer.ok || !coreAnswer.core_id) {
    return {
      verdict: { bucket: "cant", reason: coreAnswer.error || `${name} installed it, but the game did not appear`, include: false },
      include: false,
    };
  }
  const coreId = coreAnswer.core_id;
  const base: BatchRow = { ...row, path: game.eboot, probe: null, coreId, titleId: game.title_id };
  const looked = await lookUp(base, coreId, "", game.title);
  return {
    path: game.eboot,
    probe: null,
    coreId,
    systemId: "",
    // Vita3K starts the title id; the other two start the eboot.
    titleId: system === "vita" ? game.title_id : "",
    title: game.title,
    needs: await needsFor(coreId),
    ...looked,
    include: true,
  };
}

/** Probe one file and look it up: everything the review shows for it. */
async function examine(row: BatchRow, single = false): Promise<Partial<BatchRow>> {
  try {
    const probe = await probeRom(row.path);
    const packaged = probe.ps4_package
      ? (["ps4", probe.ps4_package] as const)
      : probe.vita_package
        ? (["vita", probe.vita_package] as const)
        : probe.ps3_package ? (["ps3", probe.ps3_package] as const) : null;
    // A package already installed is the game inside it, not a package.
    if (packaged && packaged[1].installed) {
      return await packagedGame({ ...row, probe }, packaged[0], packaged[1].title_id);
    }

    let installable: InstallableCore[] = [];
    if (!probe.suggested_core_id && !packaged && !probe.save_backup && !probe.rom_patch
      && !probe.game_content && !probe.archived_content && !probe.can_unpack) {
      installable = await suggestCoresForExtension(probe.match_extension).catch(() => []);
    }
    const early = classifyProbe(probe, installable.length, retroarchFound);
    // A package, or a file whose unpacked form is known (an .nsz, a zipped
    // Xbox 360 package), is looked up by its name now, so the row has its
    // cover before anything installs or unpacks.
    const into = unpacksTo(probe);
    if (early && (packaged || into)) {
      const system = packaged
        ? { ps3: "Sony - PlayStation 3", ps4: "Sony - PlayStation 4",
          vita: "Sony - PlayStation Vita" }[packaged[0]]
        : into!.system;
      const preview = await lookUp({ ...row, probe }, "", system, probe.provisional_title);
      // What will run it once unpacked, so its requirements are said now.
      const runner = into
        ? (probe.all_cores ?? []).find((core) => core.extensions.includes(into.extension))
        : undefined;
      const needs = runner ? await needsFor(runner.id) : NO_NEEDS;
      // Judged as what it unpacks to, which is what the emulator gets.
      const verdict = early.blocked || !into ? early : waitingFor(needs, early, `game.${into.extension}`);
      return {
        probe, title: preview.title ?? probe.provisional_title, resolved: preview.resolved ?? null,
        systemId: system, verdict, include: verdict.include, needs,
      };
    }
    if (early) {
      return {
        probe, title: probe.provisional_title, verdict: early, include: early.include,
        installable, installableId: installable[0]?.id ?? "",
      };
    }

    const coreId = probe.suggested_core_id;
    const systemId = chooseSystem(probe, coreId);
    const discs = single ? [] : probe.disc_set?.length >= 2 ? probe.disc_set : [];
    const base = { ...row, probe, title: probe.provisional_title };
    const looked = await lookUp(base, coreId, systemId);
    const patch: Partial<BatchRow> = {
      probe, coreId, systemId, discs, title: probe.provisional_title,
      needs: await needsFor(coreId), ...looked,
    };
    // A set is ready like any game: the row says it goes in as one, and the
    // Discs line on its page is where that changes.
    patch.verdict = waitingFor(patch.needs!, patch.verdict!, row.path);
    patch.include = patch.verdict.include;
    return patch;
  } catch (error) {
    logError("batch probe failed", error);
    return {
      verdict: { bucket: "cant", reason: "Could not read the file", include: false },
      include: false,
    };
  }
}

/** A file the transfer list already knows is not a game. */
function knownOther(file: BatchFile): Partial<BatchRow> {
  const owner = file.file?.game_content;
  const disc = file.file?.disc_for;
  const label = file.other === "content" && owner
    ? `${owner.label}${owner.title ? ` for ${owner.title}` : ""}`
    : file.other === "disc" && disc ? `Disc ${disc.disc} of ${disc.title}` : "";
  return { verdict: otherVerdict(file.other!, label), include: false };
}

async function checkOne(file: BatchFile, asked: number): Promise<void> {
  const row = rowAt(file.path);
  if (!row) return;
  const patch = file.other
    ? knownOther(file)
    : file.packaged
      ? await packagedGame(row, file.packaged.system, file.packaged.titleId)
      : await examine(row, file.single);
  if (generation !== asked) return;
  updateRow(file.path, patch);
  update({ done: batch.done + 1 });
}

/**
 * Check every game row again, as things stand now. A kept review predates
 * whatever was installed, removed or sent since: an emulator, a core, a BIOS,
 * keys. What the user chose stays where it still applies.
 */
async function recheckAll(): Promise<void> {
  const asked = generation;
  needsCache.clear();
  const rows = batch.rows.filter((row) => row.outcome === "" && !row.busy && row.verdict.bucket !== "other");
  for (const row of rows) updateRow(row.path, { busy: true });
  await Promise.all(rows.map(async (row) => {
    // An installed package's row is its game already; only its needs move.
    const patch = row.probe === null && row.coreId
      ? { needs: await needsFor(row.coreId) }
      : withChoices(row, await examine(row, row.discs.length < 2));
    if (generation !== asked) return;
    updateRow(row.path, { ...patch, busy: false });
  }));
}

/** A fresh examination, with the user's choices put back where they apply. */
function withChoices(row: BatchRow, fresh: Partial<BatchRow>): Partial<BatchRow> {
  const patch = { ...fresh };
  const verdict = patch.verdict ?? row.verdict;
  // The core picked by hand, while it is still installed and runs the file.
  if (row.corePicked && patch.probe?.all_cores?.some((core) => core.id === row.coreId) && !verdict.step) {
    patch.coreId = row.coreId;
    patch.corePicked = true;
  }
  if (row.systemPicked) Object.assign(patch, { systemId: row.systemId, systemPicked: true });
  if (row.discs.length >= 2) Object.assign(patch, { discs: row.discs, discMode: row.discMode });
  if (row.fixed) Object.assign(patch, { title: row.title, resolved: row.resolved, fixed: true });
  // Unticked by hand stays unticked; a block wins either way (see unblock).
  const unticked = !row.include && row.verdict.include && !row.verdict.blocked;
  if (unticked) patch.include = false;
  // A row the user fixed keeps its section and says so, unless now blocked.
  if (row.fixed && !verdict.blocked && !verdict.step && verdict.bucket !== "cant") {
    patch.verdict = { ...verdict, bucket: row.verdict.bucket, reason: "Chosen by you", include: true };
    if (!unticked) patch.include = true;
  }
  return patch;
}

/**
 * Fold the rows that are a disc of another row's set into that row, so a set
 * sent without its playlist is one row; whether it is one game is still asked.
 */
function mergeDiscSets(rows: BatchRow[]): BatchRow[] {
  const covered = new Set<string>();
  for (const row of rows) {
    if (row.discs.length < 2 || covered.has(row.path)) continue;
    for (const disc of row.discs) {
      const path = `${folderOf(row.path)}/${disc}`;
      if (path !== row.path) covered.add(path);
    }
  }
  return rows.filter((row) => !covered.has(row.path));
}

/**
 * Pick up the batch already checked for these same files, else start one.
 * B hides the review rather than discarding it, so opening it again does not
 * cost the check a second time.
 */
export function resumeOrStartBatch(files: BatchFile[]): void {
  const asked = new Set(files.map((file) => file.path));
  const held = new Set(batch.rows.map((row) => row.path).concat(
    batch.rows.flatMap((row) => discPaths(row)),
  ));
  const same = files.length > 0 && [...asked].every((path) => held.has(path)) &&
    batch.rows.every((row) => asked.has(row.path) || row.titleId || row.path.endsWith("eboot.bin"));
  if (batch.phase === "checking" && same) return;
  if (batch.phase === "review" && same) {
    void recheckAll();
    return;
  }
  void startBatch(files);
}

/** The other discs a merged row stands for. */
function discPaths(row: BatchRow): string[] {
  return row.discs.map((disc) => `${folderOf(row.path)}/${disc}`);
}

/** Check every file in `files` and open the review when all are in. */
export async function startBatch(files: BatchFile[]): Promise<void> {
  generation += 1;
  const asked = generation;
  needsCache.clear();
  fetched.clear();
  update({ phase: "checking", done: 0, total: files.length, current: "", rows: files.map(newRow) });
  await clearStashedArt().catch(() => undefined);
  retroarchFound = await getStatus().then((status) => status.found, () => true);
  const queue = [...files];
  const worker = async () => {
    for (let file = queue.shift(); file; file = queue.shift()) {
      if (generation !== asked) return;
      await checkOne(file, asked);
    }
  };
  await Promise.all(Array.from({ length: PARALLEL }, worker));
  if (generation !== asked) return;
  update({ phase: "review", rows: mergeDiscSets(batch.rows) });
}

// --- changes made on the review -------------------------------------------

export function setIncluded(path: string, include: boolean): void {
  // A blocked game stays off until what blocks it is done.
  if (include && rowAt(path)?.verdict.blocked) return;
  updateRow(path, { include });
}

/** A fixed row stays in its section, so nothing moves under the cursor. */
function fixedVerdict(path: string): Verdict {
  const row = rowAt(path);
  const verdict = row?.verdict ?? { bucket: "check" as const, reason: "", include: true };
  // A row that still has a step keeps saying what Add will do first.
  return { ...verdict, reason: verdict.step ? verdict.reason : "Chosen by you",
    include: !verdict.blocked };
}

/**
 * The system a row is added as, picked by hand. Looked up again for its cover,
 * unless the game was already picked by hand too.
 */
export async function setSystemFor(path: string, systemId: string): Promise<void> {
  const row = rowAt(path);
  if (!row || row.systemId === systemId) return;
  const asked = generation;
  updateRow(path, { systemId, systemPicked: true, busy: !row.fixed, include: true, verdict: fixedVerdict(path) });
  if (row.fixed) return;
  const patch = await lookUp({ ...row, systemId }, row.coreId, systemId);
  if (generation !== asked) return;
  updateRow(path, { resolved: patch.resolved, title: patch.title, busy: false });
}

/**
 * The emulator for one row, picked in its Fix dialog: a file taken for the
 * wrong platform usually needs a different emulator, not another system of
 * the same one. Looked up again unless the game was picked by hand.
 */
export async function setRowCore(path: string, coreId: string): Promise<void> {
  const row = rowAt(path);
  if (!row || row.coreId === coreId) return;
  const asked = generation;
  const systemId = chooseSystem(row.probe, coreId, row.systemPicked ? row.systemId : "");
  updateRow(path, {
    coreId, systemId, corePicked: true, busy: !row.fixed, include: true,
    verdict: fixedVerdict(path), needs: await needsFor(coreId),
  });
  if (row.fixed) return;
  const patch = await lookUp({ ...row, coreId, systemId }, coreId, systemId);
  if (generation !== asked) return;
  updateRow(path, { resolved: patch.resolved, title: patch.title, busy: false });
}

/** Look a row up again, for a lookup whose answer never came. */
export async function lookUpAgain(path: string): Promise<void> {
  const row = rowAt(path);
  if (!row || !row.coreId) return;
  const asked = generation;
  updateRow(path, { busy: true });
  const patch = await lookUp(row, row.coreId, row.systemId, row.fixed ? row.title : "");
  if (generation !== asked) return;
  updateRow(path, { ...patch, ...(row.fixed ? { title: row.title } : {}), busy: false });
}

/**
 * Look every row up again that nobody fixed by hand: a SteamGridDB key set up
 * from the review's own prompt finds what the first lookup, without one, did
 * not.
 */
export async function lookUpAll(): Promise<void> {
  const asked = generation;
  const rows = batch.rows.filter((row) => row.coreId && !row.fixed && !row.busy
    && (row.verdict.bucket === "ready" || row.verdict.bucket === "check"));
  for (const row of rows) updateRow(row.path, { busy: true });
  await Promise.all(rows.map(async (row) => {
    const patch = await lookUp(row, row.coreId, row.systemId);
    if (generation !== asked) return;
    updateRow(row.path, { ...patch, busy: false });
  }));
}

export function setTitle(path: string, title: string): void {
  updateRow(path, { title, include: true, fixed: true, verdict: fixedVerdict(path) });
}

export function setDiscMode(path: string, discMode: DiscMode): void {
  updateRow(path, { discMode, include: true, verdict: fixedVerdict(path) });
}

/** A disc picked by hand into the set, for names the rules cannot match. */
export function setDiscs(path: string, discs: string[]): void {
  updateRow(path, { discs, discMode: "one", include: true, verdict: fixedVerdict(path) });
}

export function setInstallable(path: string, coreId: string): void {
  updateRow(path, { installableId: coreId });
}

/**
 * The game picked by hand for a row. Its artwork is kept on the row rather
 * than stashed: only the few rows fixed this way carry it.
 */
export function setPickedGame(path: string, title: string, picked: Extract<AppliedArt, { ok: true }>): void {
  const row = rowAt(path);
  if (!row) return;
  // A row whose lookup failed has nothing to build on.
  const base = row.resolved ?? {
    title, system: row.systemId, matched_name: "", match_kind: "none" as const,
    title_source: "filename" as const, core_id: row.coreId, rom_path: row.path,
    art: {}, art_source: "none" as const, art_game_name: "", art_key: "",
  };
  updateRow(path, {
    title,
    include: true,
    fixed: true,
    verdict: fixedVerdict(path),
    resolved: {
      ...base,
      art: picked.art,
      art_source: picked.art_source,
      art_game_name: picked.art_game_name,
      art_key: "",
    },
  });
}

/**
 * Run every row of one extension with `coreId`, where that core can run it,
 * and look each up again: the system, and so the artwork, may change with it.
 */
export async function setCoreFor(extension: string, coreId: string): Promise<void> {
  const rows = batch.rows.filter(
    (row) =>
      row.probe?.match_extension === extension &&
      (row.verdict.bucket === "ready" || row.verdict.bucket === "check") &&
      !row.verdict.step &&
      !row.corePicked &&
      row.coreId !== coreId &&
      row.probe.matching_cores.some((core) => core.id === coreId),
  );
  const asked = generation;
  const systemFor = (row: BatchRow) => chooseSystem(row.probe, coreId, row.systemPicked ? row.systemId : "");
  const needs = await needsFor(coreId);
  for (const row of rows) {
    updateRow(row.path, { coreId, systemId: systemFor(row), busy: !row.fixed, needs });
  }
  await Promise.all(
    rows.filter((row) => !row.fixed).map(async (row) => {
      const systemId = systemFor(row);
      const patch = await lookUp({ ...row, coreId, systemId }, coreId, systemId);
      if (generation !== asked) return;
      updateRow(row.path, { ...patch, busy: false });
    }),
  );
}

// --- steps: what a file needs before it is a game ----------------------------

/**
 * Do what a row needs before it can be added, and check what came of it.
 * Returns the paths the row now stands for: one, several when a zip held
 * several files, none when the step failed.
 */
export async function runStep(path: string): Promise<string[]> {
  const row = rowAt(path);
  const step = row?.verdict.step;
  if (!row || !step || row.busy) return [];
  updateRow(path, { busy: true, error: "", stepStatus: "Starting...", stepPercent: -1 });
  try {
    if (step === "unpack") return await unpackStep(row);
    if (step === "package") return await packageStep(row);
    if (step === "emulator") return await emulatorStep(row);
    if (step === "core") return await coreStep(row);
    return [];
  } catch (error) {
    logError(`batch step ${step} failed`, error);
    updateRow(path, {
      busy: false, stepStatus: "",
      error: error instanceof Error ? error.message : "That did not work.",
    });
    return [];
  }
}

function failStep(path: string, error: string): string[] {
  updateRow(path, { busy: false, stepStatus: "", error });
  return [];
}

/** Probe what is there now and put it on the row, keeping the row's place. */
async function reexamine(path: string): Promise<string[]> {
  const row = rowAt(path);
  if (!row) return [];
  const patch = await examine({ ...row, verdict: { ...row.verdict, step: "" } });
  updateRow(path, { ...patch, busy: false, stepStatus: "", stepPercent: -1 });
  return [patch.path ?? path];
}

/**
 * Take apart a zip that could also be added as it is. RetroArch reads a zip
 * itself, but a disc set whose .cue names its .bin files cannot run from one,
 * and only the person looking at it knows which this is.
 */
export async function unpackRow(path: string): Promise<string[]> {
  const row = rowAt(path);
  if (!row?.probe?.can_unpack || row.busy) return [];
  updateRow(path, { verdict: { ...row.verdict, step: "unpack" } });
  return runStep(path);
}

/** Take a zip or an .nsz apart, then check what came out. */
async function unpackStep(row: BatchRow): Promise<string[]> {
  const listener = addEventListener<[string, number]>("nsz_unpack_progress", (name, percent) => {
    if (name === row.name) updateRow(row.path, { stepStatus: "Unpacking", stepPercent: percent });
  });
  updateRow(row.path, { stepStatus: "Unpacking" });
  try {
    const result = await unpackTransferredFile(row.name);
    if (!result.ok) return failStep(row.path, result.error ?? "Could not unpack it.");
    const written = result.written ?? [];
    if (!written.length) return failStep(row.path, "Nothing came out of it.");
    const folder = folderOf(row.path);
    const [first, ...rest] = written.map((name) => ({ path: `${folder}/${name}`, name }));
    // The first file takes the row's place; any others get rows of their own
    // just after it, so a zip of a disc set reads as what it held.
    const index = batch.rows.findIndex((one) => one.path === row.path);
    const extra = rest.map(newRow);
    const rows = [...batch.rows];
    rows.splice(index, 1, { ...rows[index], path: first.path, name: first.name }, ...extra);
    update({ rows });
    const paths = [first.path, ...rest.map((one) => one.path)];
    for (const one of paths) {
      const now = rowAt(one)!;
      const patch = await examine({ ...now, verdict: { ...now.verdict, step: "" } });
      updateRow(one, { ...patch, busy: false, stepStatus: "", stepPercent: -1 });
    }
    update({ rows: mergeDiscSets(batch.rows) });
    return paths.filter((one) => rowAt(one));
  } finally {
    removeEventListener("nsz_unpack_progress", listener);
  }
}

/** Install a PS3, PS4 or Vita package, then make its game the row. */
async function packageStep(row: BatchRow): Promise<string[]> {
  const packaged = pendingPackage(row.probe);
  if (!packaged) return reexamine(row.path);
  const events = ["ps3_install_progress", "ps4_install_progress", "vita_install_progress"] as const;
  const onProgress = (_name: string, text: string, percent: number) => {
    updateRow(row.path, {
      stepStatus: text.length > 80 ? `${text.slice(0, 77)}...` : text,
      ...(percent >= 0 ? { stepPercent: Math.max(0, Math.min(100, percent)) } : {}),
    });
  };
  const listening = events.map((event) =>
    [event, addEventListener<[string, string, number]>(event, onProgress)] as const);
  try {
    updateRow(row.path, { stepStatus: "Installing the package" });
    const result = packaged.system === "ps4"
      ? await installPs4Package(row.path)
      : packaged.system === "vita"
        // The backend finds the key that licenses this package, by content id.
        ? await installVitaPackage(row.path, "")
        : await installPs3Package(row.path);
    if (!result.ok || !result.title_id) {
      return failStep(row.path, result.error ?? "The package did not install.");
    }
    const patch = await packagedGame(row, packaged.system, result.title_id);
    updateRow(row.path, { ...patch, busy: false, stepStatus: "", stepPercent: -1 });
    return [patch.path ?? row.path];
  } finally {
    for (const [event, listener] of listening) removeEventListener(event, listener);
  }
}

/**
 * Install the emulator a package needs, then install the package: one
 * intention, as in the panel this replaces. Reported by event, so the
 * listeners live here rather than in a component that unmounts meanwhile.
 */
async function emulatorStep(row: BatchRow): Promise<string[]> {
  const packaged = pendingPackage(row.probe);
  if (!packaged) return reexamine(row.path);
  const id = packaged.state.emulator_id;
  const finished = new Promise<{ ok: boolean; message: string }>((resolve) => {
    const progress = addEventListener<[string, string, number]>(
      "emulator_install_progress", (one, text, percent) => {
        if (one === id) updateRow(row.path, { stepStatus: text, stepPercent: percent });
      });
    const done = addEventListener<[string, boolean, string]>(
      "emulator_install_done", (one, ok, message) => {
        if (one !== id) return;
        removeEventListener("emulator_install_progress", progress);
        removeEventListener("emulator_install_done", done);
        resolve({ ok, message });
      });
  });
  updateRow(row.path, { stepStatus: `Installing ${packaged.state.emulator_name}` });
  const started = await installEmulator(id);
  if (!started.ok) return failStep(row.path, started.error ?? "Could not start the install.");
  const { ok, message } = await finished;
  if (!ok) return failStep(row.path, message || "The install did not complete.");
  const [now] = await reexamine(row.path);
  const after = rowAt(now);
  return after?.verdict.step === "package" ? runStep(now) : [now];
}

/** Install a core for a file nothing installed can run, then check it again. */
async function coreStep(row: BatchRow): Promise<string[]> {
  const core = row.installable.find((one) => one.id === row.installableId) ?? row.installable[0];
  if (!core) return failStep(row.path, "No core can run it.");
  updateRow(row.path, { stepStatus: `Installing ${core.display_name}` });
  const result = await installCore(core.id);
  if (!result.ok) return failStep(row.path, result.error ?? "Could not install that core.");
  needsCache.clear();
  return reexamine(row.path);
}

// --- files that belong to a game ---------------------------------------------

/** Mark a non-game row as handled, from whatever handled it. */
export function markDone(path: string, note: string): void {
  updateRow(path, { outcome: "done", busy: false, error: "", verdict: { ...rowAt(path)!.verdict, reason: note } });
}

export function markFailed(path: string, error: string): void {
  updateRow(path, { busy: false, error });
}

export function setBusy(path: string, busy: boolean): void {
  updateRow(path, { busy });
}

/** A disc of a game already added: into that game's playlist and shortcut. */
export async function joinDiscRow(path: string): Promise<void> {
  const row = rowAt(path);
  const target = row?.file?.disc_for;
  if (!row || !target) return;
  setBusy(path, true);
  try {
    const result = await joinDiscToGame(target.app_id, path);
    if (!result.ok) {
      markFailed(path, result.error ?? "Could not add the disc.");
      return;
    }
    if (result.launcher_changed && result.exe) repointShortcut(target.app_id, result.exe);
    markDone(path, `Added to ${target.title}`);
  } catch (error) {
    logError("could not add a disc to a game", error);
    markFailed(path, "Could not add the disc.");
  }
}

/** A disc of an added game as a game of its own: **Its own entry**. */
export async function discAsOwnGame(path: string): Promise<void> {
  const row = rowAt(path);
  if (!row) return;
  updateRow(path, { busy: true, file: null });
  const patch = await examine(row, true);
  updateRow(path, { ...patch, busy: false });
}

// --- adding -----------------------------------------------------------------

const ADDABLE_STEPS = new Set(["unpack", "package", "emulator", "core"]);

/** What Add takes: ticked games, and ticked files a step makes one. */
export const chosenRows = (rows: BatchRow[]): BatchRow[] =>
  rows.filter((row) => row.include && !row.busy && row.outcome === "" && !row.verdict.blocked
    && (row.verdict.bucket === "ready" || row.verdict.bucket === "check")
    && (row.verdict.step ? ADDABLE_STEPS.has(row.verdict.step) : Boolean(row.coreId)));

/** One game into Steam; each disc on its own when the row says so. */
async function addRow(row: BatchRow): Promise<void> {
  const art = row.resolved?.art_key
    ? await takeStashedArt(row.resolved.art_key)
    : row.resolved?.art ?? {};
  const resolved = row.resolved ? { ...row.resolved, art } : null;
  const title = row.title.trim() || row.name;
  const firmwareNotes = await fetchNeeded(row);
  const each = row.discs.length >= 2 && (row.discMode === "each" || discsMustSplit(row));
  const entries = each
    ? row.discs.map((disc, index) => ({
      romPath: `${folderOf(row.path)}/${disc}`, title: `${title} (Disc ${index + 1})`, discs: [] as string[],
    }))
    : [{ romPath: row.path, title, discs: row.discs }];
  const added: Added[] = [];
  const errors: string[] = [];
  for (const entry of entries) {
    const outcome = await addGameToSteam({
      romPath: entry.romPath,
      coreId: row.coreId,
      systemId: row.systemId,
      title: entry.title,
      titleId: row.titleId,
      discs: entry.discs,
      probe: row.probe,
      resolved,
    });
    if (outcome.ok) {
      // An installed package's eboot is not ours to move back.
      const filed = row.probe ? outcome.romPath : "";
      added.push({ appId: outcome.appId, filedPath: filed });
    } else {
      errors.push(outcome.error);
    }
  }
  errors.push(...firmwareNotes);
  updateRow(row.path, added.length
    ? { outcome: "added", added, error: errors.join(" ") }
    : { outcome: "failed", error: errors.join(" ") || "Could not add it." });
  // Updates and DLC sent with it went in with it: their own rows are done.
  if (added.length) {
    const sent = new Set((row.probe?.content_waiting ?? []).map((one) => one.name));
    for (const other of batch.rows) {
      if (other.verdict.other === "content" && sent.has(other.name)) {
        markDone(other.path, "Installed with its game");
      }
    }
  }
}

/** Add every ticked row, one after another, doing each one's step first. */
export async function addBatch(): Promise<void> {
  const chosen = chosenRows(batch.rows);
  update({ phase: "adding", done: 0, total: chosen.length, current: "" });
  for (const picked of chosen) {
    update({ current: picked.title });
    try {
      let paths = [picked.path];
      if (picked.verdict.step) {
        paths = await runStep(picked.path);
        if (!paths.length) {
          updateRow(picked.path, { outcome: "failed", error: rowAt(picked.path)?.error || "Its first step failed." });
        }
      }
      for (const path of paths) {
        const row = rowAt(path);
        if (!row) continue;
        // What its step left is not a game anything here runs: say so, or the
        // result reads "Added 0 games" with nothing to explain it.
        if (!row.coreId || row.verdict.step || row.verdict.bucket === "cant") {
          updateRow(path, { outcome: "failed", error: row.verdict.reason || "Nothing here runs it." });
          continue;
        }
        update({ current: row.title });
        await addRow(row);
      }
    } catch (error) {
      logError("batch add failed", error);
      updateRow(picked.path, {
        outcome: "failed",
        error: error instanceof Error ? error.message : "Could not add it.",
      });
    }
    update({ done: batch.done + 1 });
  }
  update({ phase: "done", current: "" });
}

export function closeBatch(): void {
  generation += 1;
  update(EMPTY);
  void clearStashedArt().catch(() => undefined);
}
