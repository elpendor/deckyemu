import { useEffect, useMemo, useState } from "react";
import { FaPen } from "react-icons/fa";
import { MdHideImage, MdInsertDriveFile } from "react-icons/md";
import { ConfirmModal, DialogButton, Dropdown, Focusable, ModalRoot, TextField } from "./steamui";
import { ArtPickerModal } from "./ArtPickerModal";
import { titleAfterArtPick } from "./titleFromArt";
import { discCandidate, getSettings, type Core, type PluginSettings } from "./backend";
import {
  addBatch,
  chosenRows,
  closeBatch,
  discAsOwnGame,
  discsMustSplit,
  getBatch,
  installLicenceRow,
  joinDiscRow,
  lookUpAgain,
  lookUpAll,
  markDone,
  runStep,
  setBusy,
  setCoreFor,
  setDiscMode,
  setDiscs,
  setIncluded,
  setInstallable,
  setKeyChoice,
  setPickedGame,
  setRowCore,
  setSystemFor,
  setTitle,
  subscribeBatch,
  undoBatch,
  unpackRow,
  type Batch,
  type BatchRow,
} from "./batchImport";
import type { Bucket, Step } from "./batchPlan";
import { confirmJoinDisc } from "./confirmDiscSet";
import { coreLabel, coreOptions, installableOptions, systemOptions } from "./corePicker";
import { withDisc } from "./discSet";
import { FileName } from "./FileName";
import { FileSelectionType, openFilePicker } from "./host";
import { ICON_BUTTON, ICON_BUTTON_WIDE } from "./iconButton";
import { importDefinition } from "./importDefinition";
import { installContentFor } from "./installContent";
import { openPatchInstall } from "./installPatch";
import { InstallProgress } from "./InstallProgress";
import { logError } from "./logError";
import { openManagePage } from "./manageRoute";
import { closeOpenModals, openModal } from "./modalStack";
import { openRestoreSaves } from "./openRestore";
import { ScrollList, ScrollRow } from "./ScrollList";
import { SGDB_PROMPT, sgdbKeyJustAppeared, shouldOfferSgdb } from "./sgdbPrompt";
import { showFailure } from "./showFailure";
import { SwitchLabel } from "./SwitchLabel";

const MUTED = { fontSize: "13px", opacity: 0.7 } as const;
const PROBLEM = { fontSize: "13px", color: "#e35d5d" } as const;

const HEADINGS: Record<Bucket, string> = {
  ready: "Ready",
  check: "Check these",
  other: "Other files",
  cant: "Can't be added",
};

/**
 * Where the name came from, said under it in the Fix dialog when it is a guess.
 * An exact libretro match needs no remark; the others are worth a look.
 */
const NAME_SOURCE_LABELS: Record<string, string> = {
  libretro: "",
  steamgriddb: "Named by SteamGridDB, which also supplied the artwork. Check it before adding.",
  filename: "Named from the filename: nothing recognised this game.",
  port: "Named after the port, which is the game it plays.",
};

/**
 * The step a row needs, done now from the Fix dialog. The row only says what
 * Add will do, so every row keeps the same shape; this is for doing it first.
 */
const STEP_LABELS: Record<Exclude<Step, "">, string> = {
  unpack: "Unpack now",
  package: "Install now",
  emulator: "Install now",
  core: "Install core now",
  retroarch: "Get RetroArch",
};

function useBatch(): Batch {
  const [state, setState] = useState(getBatch);
  useEffect(() => subscribeBatch(setState), []);
  return state;
}

const coreOf = (row: BatchRow) => row.probe?.all_cores?.find((core) => core.id === row.coreId);

/** "SNES", as Added games says it, from the labels the core came with. */
function systemLabel(row: BatchRow): string {
  // A core covering one system is never asked, so the lookup has the answer.
  const id = row.systemId || row.resolved?.system || "";
  if (!id) return "";
  const core = coreOf(row);
  const index = core?.databases?.indexOf(id) ?? -1;
  return (index >= 0 && core?.database_labels?.[index]?.trim()) || id.split(" - ").pop() || id;
}

const coreName = (row: BatchRow) => coreLabel(row.probe?.all_cores ?? [], row.coreId);

/** "**SNES** · bsnes · …": the system first and bold, the rest as it was. */
function Detail({ row, rest }: { row: BatchRow; rest: string[] }) {
  const system = systemLabel(row);
  const tail = [coreName(row), ...rest].filter(Boolean).join(" · ");
  return (
    <>
      {system && <span style={{ fontWeight: 600 }}>{system}</span>}
      {system && tail ? " · " : ""}
      {tail}
    </>
  );
}

/** Extensions whose rows more than one installed core could run. */
function coreChoices(rows: BatchRow[]): { extension: string; cores: Core[]; current: string; count: number }[] {
  const byExtension = new Map<string, BatchRow[]>();
  for (const row of rows) {
    const extension = row.probe?.match_extension;
    const game = row.verdict.bucket === "ready" || row.verdict.bucket === "check";
    if (!extension || !game || row.verdict.step || row.corePicked ||
      (row.probe?.matching_cores.length ?? 0) < 2) continue;
    byExtension.set(extension, [...(byExtension.get(extension) ?? []), row]);
  }
  return [...byExtension.entries()].map(([extension, list]) => {
    const counts = new Map<string, number>();
    for (const row of list) counts.set(row.coreId, (counts.get(row.coreId) ?? 0) + 1);
    const current = [...counts.entries()].sort((a, b) => b[1] - a[1])[0][0];
    return { extension, cores: list[0].probe!.matching_cores, current, count: list.length };
  });
}

/** Every warning the probe has about a file, whole, for the Fix dialog. */
function warningsOf(row: BatchRow): string[] {
  const probe = row.probe;
  const already = probe?.already_added;
  return [
    already
      ? already.same_file
        ? `${already.name || "A game"} already runs this exact file. Adding it again makes a second entry.`
        : `${already.name || "A game"} runs a file with this name from somewhere else, so this may be the same game sent twice.`
      : "",
    probe?.unsupported_extension ? `.${probe.extension} is normally a save or config file, not a ROM.` : "",
    probe?.track_warning ?? "",
    probe?.disc_folder_warning ?? "",
    probe?.disc_warning ?? "",
    probe?.dump_warning ?? "",
    row.needs ? `${row.needs}. The game will be added, but is unlikely to start until that is supplied (Emulators tab, under BIOS and firmware).` : "",
    ...packageWarnings(row),
  ].filter(Boolean);
}

/** What a package needs said before it installs: its licence, and after. */
function packageWarnings(row: BatchRow): string[] {
  const probe = row.probe;
  const ps3 = probe?.ps3_package;
  const vita = probe?.vita_package;
  const waiting = probe?.ps4_package ?? vita ?? ps3;
  if (!waiting || waiting.installed) return [];
  const notes: string[] = [];
  if (!waiting.emulator_ready && waiting.needs_firmware) {
    notes.push(`${waiting.emulator_name} also needs its firmware before games start. Emulators tab, under BIOS and firmware.`);
  }
  if (ps3?.licence_state === "" && ps3.content_id) {
    notes.push(`Store games need a .rap licence. Send it to the same folder as the game and it goes in when the game does. If there is more than one .rap there, name this one ${ps3.content_id}.rap. Licence-free games work without one.`);
  } else if (ps3?.licence_state === "installed") {
    notes.push("RPCS3 already has this game's .rap, from an earlier install.");
  } else if (ps3?.licence_state === "waiting") {
    notes.push("This game's .rap is here and goes in with it.");
  }
  if (vita?.licence === false) {
    notes.push((vita.licence_candidates ?? []).length
      ? `Nothing here is named for ${vita.title_id || "this package"}, so its key cannot be matched automatically. Pick the one that came with this game below, or send it again as ${vita.licence_name || "the title id with a .zrif extension"}. The wrong key installs the whole game and then fails to decrypt it.`
      : `Vita3K decrypts a package as it installs, so its key has to be here too. Send it to the same folder as the game: a .zrif, or a .txt with the key in it, named ${vita.licence_name || "after the title id"}. Opening this review again picks it up.`);
  }
  return notes;
}

/** A labelled control on one line of the Fix dialog. */
function Line({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Focusable style={{ display: "flex", alignItems: "center", gap: "10px", marginTop: "10px" }}>
      <div style={{ flexShrink: 0, width: "90px" }}>{label}</div>
      <div style={{ flexGrow: 1, minWidth: 0 }}>{children}</div>
    </Focusable>
  );
}

/**
 * Everything about one game before it is added: its name, the game and cover,
 * the emulator and system, its discs, and what the probe warns of. What the
 * panel's single add offered, for one row of the review.
 */
function FixRowModal({ path, closeModal }: { path: string; closeModal?: () => void }) {
  const row = useBatch().rows.find((one) => one.path === path);
  const [name, setName] = useState(row?.title ?? "");
  // What the field held before anyone typed, so a picked game can rename it.
  const [automatic, setAutomatic] = useState(row?.title ?? "");
  const [everything, setEverything] = useState(false);
  const [error, setError] = useState("");
  if (!row) return null;
  const capsule = row.resolved?.art?.capsule?.data;
  // Only for a core covering several systems, as in the panel.
  const systems = systemOptions(coreOf(row));
  const matching = row.probe?.matching_cores ?? [];
  const all = row.probe?.all_cores ?? [];
  const cores = everything || matching.length === 0 ? all : matching;
  const candidates = row.probe?.vita_package?.licence_candidates ?? [];
  const warnings = warningsOf(row);

  const choose = () =>
    openModal(
      <ArtPickerModal
        romPath={row.path}
        coreId={row.coreId}
        initialQuery={name}
        onApplied={(picked) => {
          const title = titleAfterArtPick(name, automatic, picked.suggested_title);
          setName(title);
          setAutomatic(title);
          setPickedGame(row.path, title, picked);
        }}
      />,
    );

  // A disc the naming rules cannot see, picked by hand from the same folder:
  // a playlist names files beside itself, so that is the only place one can be.
  const pickDisc = async () => {
    const folder = row.path.slice(0, row.path.lastIndexOf("/"));
    let picked: { path: string; realpath: string } | undefined;
    try {
      picked = await openFilePicker(FileSelectionType.FILE, folder, true, true,
        undefined, undefined, false, true);
    } catch (pickError) {
      if (!String(pickError ?? "").toLowerCase().includes("cancel")) {
        logError("disc picker failed", pickError);
        setError("Could not open the file browser.");
      }
      return;
    }
    const chosen = picked?.realpath || picked?.path || "";
    if (!chosen) return;
    try {
      const answer = await discCandidate(chosen, folder);
      if (!answer.ok) {
        setError(answer.error);
        return;
      }
      const next = withDisc(row.discs, row.name, answer.name);
      if (next) setDiscs(row.path, next);
      setError("");
    } catch (discError) {
      logError("could not check a disc", discError);
      setError("Could not check that file.");
    }
  };

  const done = () => {
    if (name.trim() && name !== row.title) setTitle(row.path, name.trim());
    closeModal?.();
  };

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "4px" }}>Fix this game</div>
      <div style={{ ...MUTED, marginBottom: "12px", overflowWrap: "anywhere" }}>{row.name}</div>
      {/* Short enough that the heading and two rows of buttons still fit. */}
      <ScrollList style={{ maxHeight: "40vh" }}>
        <Focusable style={{ display: "flex", gap: "12px", alignItems: "flex-start" }}>
          <Cover capsule={capsule} width={64} />
          <div style={{ flexGrow: 1, minWidth: 0 }}>
            <TextField
              label="Name in Steam"
              value={name}
              bShowClearAction
              style={{ paddingRight: "2.6em" }}
              onChange={(event) => setName(event.target.value)}
            />
            <div style={{ ...MUTED, marginTop: "6px" }}>
              {row.busy ? "Looking up..." : row.resolved?.art_game_name ? `Artwork: ${row.resolved.art_game_name}` : "No artwork found"}
            </div>
            {!row.fixed && row.resolved && NAME_SOURCE_LABELS[row.resolved.title_source] && (
              <div style={{ ...MUTED, marginTop: "4px" }}>{NAME_SOURCE_LABELS[row.resolved.title_source]}</div>
            )}
          </div>
        </Focusable>

        {warnings.map((text) => (
          <ScrollRow key={text}>
            <div style={{ fontSize: "13px", marginTop: "10px" }}>{text}</div>
          </ScrollRow>
        ))}

        {/* A file taken for the wrong platform usually needs another emulator,
            and the picker for its file type would change every such file. */}
        {cores.length > 1 && (
          <Line label="Emulator">
            <Dropdown
              rgOptions={coreOptions(cores)}
              selectedOption={row.coreId}
              onChange={(option) => void setRowCore(row.path, String(option.data))}
            />
          </Line>
        )}
        {matching.length > 0 && all.length > matching.length && (
          <Focusable style={{ marginTop: "8px" }}>
            <DialogButton
              onClick={() => setEverything(!everything)}
              style={{ ...ICON_BUTTON_WIDE, justifyContent: "flex-start", width: "100%" }}
            >
              <SwitchLabel name="Show everything installed" on={everything} />
            </DialogButton>
          </Focusable>
        )}
        {systems.length > 0 && (
          <Line label="System">
            <Dropdown
              rgOptions={systems}
              selectedOption={row.systemId}
              onChange={(option) => void setSystemFor(row.path, String(option.data))}
            />
          </Line>
        )}
        {discsMustSplit(row) && (
          <ScrollRow>
            <div style={{ fontSize: "13px", marginTop: "10px" }}>
              {coreName(row) || "This emulator"} cannot be given a playlist, so each of
              the {row.discs.length} discs is added on its own. They are filed side by side,
              so it can find the next one when it asks.
            </div>
          </ScrollRow>
        )}
        {row.discs.length >= 2 && !discsMustSplit(row) && (
          <Line label="Discs">
            <Dropdown
              rgOptions={[
                { data: "one", label: `One game of ${row.discs.length} discs` },
                { data: "each", label: "Each disc on its own" },
              ]}
              selectedOption={row.discMode}
              onChange={(option) => setDiscMode(row.path, option.data === "each" ? "each" : "one")}
            />
          </Line>
        )}
        {row.installable.length > 1 && row.verdict.step === "core" && (
          <Line label="Core">
            <Dropdown
              rgOptions={installableOptions(row.installable)}
              selectedOption={row.installableId}
              onChange={(option) => setInstallable(row.path, String(option.data))}
            />
          </Line>
        )}
        {candidates.length > 0 && (
          <Line label="Licence key">
            <Dropdown
              rgOptions={candidates.map((key) => ({ data: key, label: key }))}
              selectedOption={row.keyChoice}
              onChange={(option) => {
                setKeyChoice(row.path, String(option.data));
                setIncluded(row.path, true);
              }}
            />
          </Line>
        )}
        {error && <div style={{ ...PROBLEM, marginTop: "8px" }}>{error}</div>}
      </ScrollList>
      <Focusable flow-children="row" style={{ display: "flex", gap: "8px", marginTop: "14px", flexWrap: "wrap" }}>
        {row.verdict.step && <StepButton row={row} close={closeModal} />}
        {row.coreId && (
          <DialogButton onClick={choose} disabled={row.busy} style={{ flex: 2 }}>
            Choose the right game
          </DialogButton>
        )}
        {/* Only once a set is in play, as in the panel: a cartridge has no
            second disc, and a set the rules saw is where one can be missing. */}
        {row.coreId && !row.titleId && ((row.probe?.disc_set?.length ?? 0) > 0 || row.discs.length >= 2) && (
          <DialogButton onClick={() => void pickDisc()} disabled={row.busy} style={{ flex: 1 }}>
            Add a disc
          </DialogButton>
        )}
        {row.probe?.can_unpack && !row.verdict.step && (
          <DialogButton
            onClick={() => {
              void unpackRow(row.path);
              closeModal?.();
            }}
            disabled={row.busy}
            style={{ flex: 1 }}
          >
            Unpack instead
          </DialogButton>
        )}
        {!row.resolved && row.coreId && (
          <DialogButton onClick={() => void lookUpAgain(row.path)} disabled={row.busy} style={{ flex: 1 }}>
            Look up again
          </DialogButton>
        )}
        <DialogButton autoFocus onClick={done} style={{ flex: 1 }}>Done</DialogButton>
      </Focusable>
    </ModalRoot>
  );
}

/**
 * The cover column for a row that is not a game: the same 48px, so every
 * section's text starts in one column whatever the row is.
 */
function FileTile() {
  return (
    <div style={{ width: "48px", height: "48px", flexShrink: 0, borderRadius: "3px",
      display: "flex", alignItems: "center", justifyContent: "center",
      background: "rgba(255,255,255,0.08)" }}>
      <MdInsertDriveFile aria-hidden style={{ fontSize: "22px", opacity: 0.5 }} />
    </div>
  );
}

/** A cover, or a crossed-out image where none was found. */
function Cover({ capsule, width }: { capsule?: string; width: number }) {
  return (
    <div style={{ width: `${width}px`, height: `${width * 1.5}px`, flexShrink: 0, borderRadius: "3px",
      display: "flex", alignItems: "center", justifyContent: "center",
      background: capsule ? `center / cover no-repeat url("${capsule}")` : "rgba(255,255,255,0.08)" }}>
      {!capsule && <MdHideImage aria-label="No cover" style={{ fontSize: `${width / 2}px`, opacity: 0.5 }} />}
    </div>
  );
}

/** The row's step, as the button that does it now. **Add** does it too. */
function StepButton({ row, close }: { row: BatchRow; close?: () => void }) {
  const step = row.verdict.step;
  if (!step) return null;
  const press = () => {
    if (step === "retroarch") {
      // RetroArch is installed from its own page; the review keeps meanwhile.
      closeOpenModals();
      openManagePage("retroarch");
      return;
    }
    void runStep(row.path);
    close?.();
  };
  return (
    <DialogButton onClick={press} disabled={row.busy} style={{ flex: 1 }}>
      {STEP_LABELS[step]}
    </DialogButton>
  );
}

function GameRow({ row }: { row: BatchRow }) {
  const capsule = row.resolved?.art?.capsule?.data;
  const stepping = row.busy && Boolean(row.stepStatus);
  const rest = [
    row.discs.length >= 2
      ? row.discMode === "each" || discsMustSplit(row)
        ? `${row.discs.length} discs, each on its own`
        : `${row.discs.length} discs`
      : "",
    row.busy && !stepping ? "Looking up..." : row.verdict.reason,
    row.needs ? "BIOS missing" : "",
  ];
  return (
    <Focusable style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "4px" }}>
      {/* One size on every row: the column lines up and any cover can be checked. */}
      <Cover capsule={capsule} width={48} />
      <DialogButton
        onClick={() => setIncluded(row.path, !row.include)}
        disabled={row.busy}
        // Two lines, so the height follows the text, from the left.
        style={{ ...ICON_BUTTON_WIDE, height: "auto", minHeight: "48px", padding: "8px 16px",
          justifyContent: "flex-start", flexGrow: 1, minWidth: 0 }}
      >
        <div style={{ width: "100%", minWidth: 0 }}>
          <SwitchLabel name={row.title} on={row.include} />
          {/* The file it came from, which is how a wrong match shows. One line,
              cut in the middle so the region tags and extension stay; the
              Fix dialog has it whole. */}
          <FileName name={row.name} style={{ ...MUTED, marginLeft: "50px" }} />
          {stepping ? (
            <div style={{ marginLeft: "50px" }}>
              <InstallProgress inline label={row.stepStatus} percent={row.stepPercent} status="" />
            </div>
          ) : (
            <div style={{ ...MUTED, textAlign: "left", marginLeft: "50px" }}>
              <Detail row={row} rest={rest} />
            </div>
          )}
          {row.error && <div style={{ ...PROBLEM, textAlign: "left", marginLeft: "50px" }}>{row.error}</div>}
        </div>
      </DialogButton>
      {/* The pencil Added games uses for editing a game. */}
      <DialogButton
        aria-label="Fix"
        onClick={() => openModal(<FixRowModal path={row.path} />)}
        disabled={row.busy}
        style={{ ...ICON_BUTTON, flexShrink: 0 }}
      >
        <FaPen />
      </DialogButton>
    </Focusable>
  );
}

/**
 * A file that belongs to a game rather than being one, with the action the
 * transfer list gives it. Done when pressed, not on Add: each asks its own
 * question first -- which game a patch is for, whether a disc joins its game.
 */
function OtherRow({ row, hide }: { row: BatchRow; hide: () => void }) {
  const kind = row.verdict.other;
  const owner = row.file?.game_content ?? row.probe?.game_content;
  const act = () => {
    if (kind === "definition") {
      importDefinition(row.name, () => markDone(row.path, "Imported"));
    } else if (kind === "licence") {
      void installLicenceRow(row.path);
    } else if (kind === "content" && owner) {
      setBusy(row.path, true);
      void installContentFor(owner, row.path).then((installed) =>
        installed ? markDone(row.path, "Installed") : setBusy(row.path, false));
    } else if (kind === "patch") {
      openPatchInstall(row.path, row.name, (installed) => {
        if (installed) markDone(row.path, "Installed");
      });
    } else if (kind === "save") {
      // The restore screen is a page of its own. The review is kept, not
      // thrown away, so the rest is still there afterwards.
      hide();
      closeOpenModals();
      openRestoreSaves();
    } else if (kind === "disc" && row.file?.disc_for) {
      void confirmJoinDisc(row.file.disc_for.title, row.name).then((choice) => {
        if (choice === "set") void joinDiscRow(row.path);
        else if (choice === "single") void discAsOwnGame(row.path);
      });
    }
  };
  const label = kind === "definition" ? "Import"
    : kind === "save" ? "Restore"
      : kind === "disc" ? "Add to game"
        : kind === "firmware" || kind === "key" ? ""
          : "Install";
  const note = kind === "firmware" ? "Install it from the transfer list, where its emulator is known"
    : kind === "key" ? "" : "";
  return (
    <Focusable style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "4px" }}>
      <FileTile />
      {/* The game rows' text sits 16px into their button; this matches it. */}
      <div style={{ flexGrow: 1, minWidth: 0, padding: "6px 16px" }}>
        <FileName name={row.name} />
        <div style={MUTED}>{row.busy ? "Working..." : [row.verdict.reason, note].filter(Boolean).join(" · ")}</div>
        {row.error && <div style={PROBLEM}>{row.error}</div>}
      </div>
      {label && row.outcome !== "done" && (
        <DialogButton onClick={act} disabled={row.busy} style={{ ...ICON_BUTTON_WIDE, flexShrink: 0 }}>
          {label}
        </DialogButton>
      )}
    </Focusable>
  );
}

function CantRow({ row }: { row: BatchRow }) {
  // Nothing to press, but a ScrollRow so a controller can still scroll to it.
  return (
    <ScrollRow>
      <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "4px" }}>
        <FileTile />
        <div style={{ flexGrow: 1, minWidth: 0, padding: "6px 16px" }}>
          <FileName name={row.name} />
          <div style={MUTED}>{row.busy ? "Checking again..." : row.verdict.reason}</div>
        </div>
      </div>
    </ScrollRow>
  );
}

function Review({ batch, hide }: { batch: Batch; hide: () => void }) {
  const choices = useMemo(() => coreChoices(batch.rows), [batch.rows]);
  const buckets: Bucket[] = ["ready", "check", "other", "cant"];
  const withVitaPackage = batch.rows.some((row) => row.probe?.vita_package);
  return (
    // The pickers scroll with the rows: above them they left the list no room.
    <ScrollList style={{ maxHeight: "50vh" }}>
      {/* Says why it is here: only types more than one emulator can run. */}
      {choices.length > 0 && (
        <div style={{ ...MUTED, margin: "8px 0 4px" }}>Emulator for each file type</div>
      )}
      {choices.map(({ extension, cores, current, count }) => (
        <Focusable key={extension} style={{ display: "flex", alignItems: "center", gap: "10px", margin: "4px 0 8px" }}>
          <div style={{ fontSize: "13px", flexShrink: 0 }}>
            {cores.length} installed emulators run .{extension}
            <span style={{ opacity: 0.7 }}> ({count} file{count === 1 ? "" : "s"})</span>
          </div>
          <div style={{ flexGrow: 1 }}>
            <Dropdown
              rgOptions={coreOptions(cores)}
              selectedOption={current}
              onChange={(option) => void setCoreFor(extension, String(option.data))}
            />
          </div>
        </Focusable>
      ))}
      {buckets.map((bucket) => {
        const rows = batch.rows.filter((row) => row.verdict.bucket === bucket
          // A Vita key goes in with its package, whose row says so.
          && !(row.verdict.other === "key" && withVitaPackage));
        if (!rows.length) return null;
        return (
          <div key={bucket}>
            <div style={{ ...MUTED, margin: "8px 0 4px" }}>
              {HEADINGS[bucket]} ({rows.length})
            </div>
            {rows.map((row) =>
              bucket === "other" ? <OtherRow key={row.path} row={row} hide={hide} />
                : bucket === "cant" ? <CantRow key={row.path} row={row} />
                  : <GameRow key={row.path} row={row} />)}
          </div>
        );
      })}
    </ScrollList>
  );
}

/**
 * Adding games: the review, and the progress of adding them. Opened from the
 * transfer list (**Add** on one file, **Add all…** on everything) and from the
 * panel's file browser, after `startBatch`.
 */
export function BatchImportModal({ closeModal }: { closeModal?: () => void }) {
  const batch = useBatch();
  const { phase, rows } = batch;
  const chosen = chosenRows(rows);
  const added = rows.filter((row) => row.outcome === "added");
  const games = added.reduce((sum, row) => sum + row.added.length, 0);
  const failed = rows.filter((row) => row.outcome === "failed");
  const busy = phase === "adding" || rows.some((row) => row.busy);
  const [settings, setSettings] = useState<PluginSettings | null>(null);
  useEffect(() => {
    getSettings().then((read) => {
      setSettings(read);
      // Back from setting up a key: what was found without one is worth asking
      // again.
      if (sgdbKeyJustAppeared(read) && getBatch().phase === "review") void lookUpAll();
    }, () => undefined);
  }, []);

  const close = () => {
    closeBatch();
    closeModal?.();
  };
  // B during the check or the review hides it and keeps the results: opening
  // it again with the same files brings them back. Only Cancel throws them
  // away.
  const hide = () => closeModal?.();
  const back = phase === "checking" || phase === "review" ? hide : close;

  const undo = () =>
    openModal(
      <ConfirmModal
        strTitle={`Remove the ${games} game${games === 1 ? "" : "s"} just added?`}
        strDescription="They come out of Steam and your library, and their files go back to the transfer folder."
        strOKButtonText="Remove"
        bDestructiveWarning
        onOK={() => {
          void undoBatch().then(
            ({ kept }) => {
              if (kept) {
                showFailure(
                  "Removed, but some files stayed filed",
                  `${kept} could not go back to the transfer folder, usually because a file of the same name is already there. They are still in deckyemu/roms.`,
                );
              }
            },
            (error) => {
              logError("batch undo failed", error);
              showFailure("Could not remove them all", error);
            },
          );
        }}
      />,
    );

  return (
    <ModalRoot closeModal={phase === "adding" ? undefined : back} bAllowFullSize>
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "4px" }}>
        {phase === "done" || phase === "undone" ? "Added" : "Add games"}
      </div>

      {phase === "checking" && (
        <InstallProgress
          label={`Checking ${batch.done} of ${batch.total} file${batch.total === 1 ? "" : "s"}`}
          percent={batch.total ? Math.round((batch.done / batch.total) * 100) : 0}
          status=""
        />
      )}

      {phase === "review" && (
        <>
          <div style={{ ...MUTED, marginBottom: "8px" }}>
            Untick anything that looks wrong; the pencil fixes a game.
          </div>
          {/* The panel said this under the artwork; here it is said once. */}
          {shouldOfferSgdb(settings) && (
            <Focusable style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "8px" }}>
              <div style={{ ...MUTED, flexGrow: 1 }}>{SGDB_PROMPT.label}. {SGDB_PROMPT.description}</div>
              <DialogButton
                onClick={() => {
                  hide();
                  closeOpenModals();
                  openManagePage("artwork");
                }}
                style={{ ...ICON_BUTTON_WIDE, flexShrink: 0 }}
              >
                {SGDB_PROMPT.action}
              </DialogButton>
            </Focusable>
          )}
          <Review batch={batch} hide={hide} />
        </>
      )}

      {phase === "adding" && (
        <InstallProgress
          label={`Adding ${batch.current} (${Math.min(batch.done + 1, batch.total)} of ${batch.total})`}
          percent={batch.total ? Math.round((batch.done / batch.total) * 100) : 0}
          status=""
        />
      )}

      {phase === "done" && (
        <div style={{ fontSize: "14px", margin: "8px 0" }}>
          <div>Added {games} game{games === 1 ? "" : "s"}.</div>
          <ScrollList style={{ maxHeight: "40vh", marginTop: "8px" }}>
            {added.map((row) => (
              <ScrollRow key={row.path}>
                <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "4px" }}>
                  <Cover capsule={row.resolved?.art?.capsule?.data} width={24} />
                  <div style={{ minWidth: 0 }}>
                    <div>{row.title}{row.added.length > 1 ? ` (${row.added.length} entries)` : ""}</div>
                    <div style={MUTED}><Detail row={row} rest={[]} /></div>
                    {row.error && <div style={PROBLEM}>{row.error}</div>}
                  </div>
                </div>
              </ScrollRow>
            ))}
            {failed.map((row) => (
              <ScrollRow key={row.path}>
                <div style={{ marginBottom: "6px" }}>
                  <div>{row.title} wasn't added</div>
                  <div style={MUTED}>{row.error}</div>
                </div>
              </ScrollRow>
            ))}
          </ScrollList>
          {games > 0 && (
            <div style={{ ...MUTED, marginTop: "8px" }}>Undo is here until you close this.</div>
          )}
        </div>
      )}

      {phase === "undone" && (
        <div style={{ fontSize: "14px", margin: "8px 0" }}>
          Removed. Their files are back in the transfer folder.
        </div>
      )}

      {/* Keyed by phase so its buttons mount anew and `autoFocus` takes. */}
      <Focusable key={phase} flow-children="row" style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
        {phase === "review" && (
          <DialogButton autoFocus onClick={() => void addBatch()} disabled={busy || chosen.length === 0}>
            Add {chosen.length} game{chosen.length === 1 ? "" : "s"}
          </DialogButton>
        )}
        {phase === "done" && games > 0 && (
          <DialogButton onClick={undo}>Undo</DialogButton>
        )}
        {phase !== "adding" && (
          <DialogButton
            // The Add button that had focus is gone; Close, not Undo, so a
            // stray press of A after adding keeps the games.
            autoFocus={phase !== "review"}
            onClick={close}
          >
            {phase === "review" || phase === "checking" ? "Cancel" : "Close"}
          </DialogButton>
        )}
      </Focusable>
    </ModalRoot>
  );
}
