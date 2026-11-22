import { useEffect, useMemo, useRef, useState } from "react";
import { FaPen } from "react-icons/fa";
import { MdCheck, MdChevronRight, MdHideImage, MdInsertDriveFile } from "react-icons/md";
import { DialogButton, Dropdown, Focusable, ModalRoot, TextField, type DropdownOption } from "./steamui";
import { titleAfterArtPick } from "./titleFromArt";
import {
  applyArtCandidate,
  discCandidate,
  getSettings,
  listArtCandidates,
  type AppliedArt,
  type Core,
  type PluginSettings,
} from "./backend";
import {
  addBatch,
  chosenRows,
  closeBatch,
  discAsOwnGame,
  discsMustSplit,
  getBatch,
  joinDiscRow,
  lookUpAgain,
  lookUpAll,
  markDone,
  setBusy,
  setCoreFor,
  setDiscMode,
  setDiscs,
  setIncluded,
  setInstallable,
  setPickedGame,
  setRowCore,
  setSystemFor,
  sendFor,
  setTitle,
  contentSummary,
  contentWithGames,
  subscribeBatch,
  unpackRow,
  type Batch,
  type BatchRow,
} from "./batchImport";
import type { Bucket } from "./batchPlan";
import { confirmJoinDisc } from "./confirmDiscSet";
import { coreLabel, coreOptions, installableOptions, systemOptions } from "./corePicker";
import { discSetLabel, withDisc, withoutDiscTag } from "./discSet";
import { FileName } from "./FileName";
import { FileSelectionType, openFilePicker } from "./host";
import { ICON_BUTTON, ICON_BUTTON_WIDE } from "./iconButton";
import { importDefinition } from "./importDefinition";
import { installContentFor } from "./installContent";
import { openPatchInstall } from "./installPatch";
import { InstallProgress } from "./InstallProgress";
import { logError } from "./logError";
import { openManagePage } from "./manageRoute";
import { closeOpenModals } from "./modalStack";
import { openRestoreSaves } from "./openRestore";
import { ScrollList, ScrollRow } from "./ScrollList";
import { SGDB_PROMPT, sgdbKeyJustAppeared, shouldOfferSgdb } from "./sgdbPrompt";
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

/** The emulator's name; a package's own, which the probe may not list. */
function coreName(row: BatchRow): string {
  const packaged = row.probe?.ps4_package ?? row.probe?.vita_package ?? row.probe?.ps3_package;
  if (packaged && row.coreId === `emu:${packaged.emulator_id}`) return packaged.emulator_name;
  return coreLabel(row.probe?.all_cores ?? [], row.coreId);
}

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
    row.needs.download.length
      ? `${row.needs.emulator} needs ${row.needs.download.map((one) => one.name).join(" and ")}; it downloads from Sony as the game is added.`
      : "",
    sendFor(row).length
      ? `${row.needs.emulator} asks for ${sendFor(row).join(", ")}. Many games run without it; if this one does not, send it from the transfer page.`
      : "",
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
  if (ps3?.licence_state === "" && ps3.content_id && ps3.licence_needed) {
    notes.push(`This game needs its .rap licence. Send it to the same folder as the game, named ${ps3.content_id}.rap if more than one is there, and open this again.`);
  } else if (ps3?.licence_state === "" && ps3.content_id && ps3.licence_needed !== false) {
    notes.push(`Store games need a .rap licence. Send it to the same folder as the game and it goes in when the game does. If there is more than one .rap there, name this one ${ps3.content_id}.rap. Licence-free games work without one.`);
  } else if (ps3?.licence_state === "installed") {
    notes.push("RPCS3 already has this game's .rap, from an earlier install.");
  } else if (ps3?.licence_state === "waiting") {
    notes.push("This game's .rap is here and goes in with it.");
  }
  if (vita?.licence === false) {
    notes.push((vita.licence_candidates ?? []).length
      ? `The key here (${(vita.licence_candidates ?? []).join(", ")}) is for another game. Keys are matched to their package by what they unlock, so send this game's .zrif, under any name.`
      : `Vita3K decrypts a package as it installs, so its key has to be here too: send its .zrif, or a .txt with the key in it, under any name. Opening this again picks it up.`);
  } else if (vita) {
    notes.push("Its licence key is here and was matched to it by what it unlocks.");
  }
  return notes;
}

/** One game the artwork search found, as a pickable row. */
interface Candidate {
  key: string;
  source: "libretro" | "steamgriddb";
  ref: string;
  system: string;
  label: string;
  sublabel: string;
}

const CANDIDATES_SHOWN = 6;

/**
 * The search for the right game, inside the row it is for: the closest matches
 * listed as soon as the editor opens, and a search box for when none is right.
 * Picking one sets the row's cover, and its name unless one was typed.
 */
function Candidates({ row, name, onPicked }: {
  row: BatchRow;
  name: string;
  onPicked: (picked: Extract<AppliedArt, { ok: true }>) => void;
}) {
  const [query, setQuery] = useState(name);
  const [found, setFound] = useState<Candidate[] | null>(null);
  const [applying, setApplying] = useState("");
  const [error, setError] = useState("");

  const search = async (term: string) => {
    setFound(null);
    setError("");
    try {
      const result = await listArtCandidates(row.path, row.coreId, term);
      const rows: Candidate[] = [
        ...(result.steamgriddb ?? []).map((hit) => ({
          key: `sgdb-${hit.id}`, source: "steamgriddb" as const, ref: String(hit.id), system: "",
          label: hit.name, sublabel: `SteamGridDB${hit.year ? ` · ${hit.year}` : ""}`,
        })),
        ...(result.libretro ?? []).map((hit) => ({
          key: `libretro-${hit.system}-${hit.name}`, source: "libretro" as const, ref: hit.name,
          system: hit.system, label: hit.name, sublabel: `libretro · ${hit.system.split(" - ").pop()}`,
        })),
      ];
      setFound(rows.slice(0, CANDIDATES_SHOWN));
    } catch (searchError) {
      logError("artwork search failed", searchError);
      setError("Could not search for artwork.");
      setFound([]);
    }
  };

  // Once, when the editor opens; the search box does the rest.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => void search(name), []);

  const pick = async (candidate: Candidate) => {
    setApplying(candidate.key);
    setError("");
    try {
      const result = await applyArtCandidate(candidate.source, candidate.ref, candidate.system, candidate.label);
      if (result.ok) onPicked(result);
      else setError(result.error);
    } catch (applyError) {
      logError("could not apply artwork", applyError);
      setError("Could not download that artwork.");
    } finally {
      setApplying("");
    }
  };

  // Marked once: two entries can share a name (a remake and its original).
  const inUse = found?.find((one) => one.label === row.resolved?.art_game_name)?.key ?? "";
  return (
    <>
      <Focusable style={{ display: "flex", gap: "8px", marginTop: "10px", alignItems: "flex-end" }}>
        <div style={{ flexGrow: 1, minWidth: 0 }}>
          <TextField label="Search for the game" value={query} onChange={(event) => setQuery(event.target.value)} />
        </div>
        <DialogButton
          onClick={() => void search(query)}
          disabled={!query.trim() || found === null}
          style={{ ...ICON_BUTTON_WIDE, flexShrink: 0 }}
        >
          Search
        </DialogButton>
      </Focusable>
      {found === null && <div style={{ ...MUTED, marginTop: "8px" }}>Searching...</div>}
      {found?.length === 0 && !error && (
        <div style={{ ...MUTED, marginTop: "8px" }}>Nothing found for that name.</div>
      )}
      {found?.map((candidate, index) => (
        <Focusable key={candidate.key} style={{ marginTop: "4px" }}>
          <DialogButton
            autoFocus={inUse ? candidate.key === inUse : index === 0}
            onClick={() => void pick(candidate)}
            onOKActionDescription="Choose"
            disabled={Boolean(applying)}
            style={{ ...ICON_BUTTON_WIDE, height: "auto", minHeight: "44px", padding: "6px 14px",
              justifyContent: "flex-start", width: "100%" }}
          >
            <div style={{ textAlign: "left", minWidth: 0 }}>
              <div>
                {applying === candidate.key ? "Applying..." : candidate.label}
                {candidate.key === inUse && <span style={{ opacity: 0.7 }}> · in use</span>}
              </div>
              <div style={MUTED}>{candidate.sublabel}</div>
            </div>
          </DialogButton>
        </Focusable>
      ))}
      {error && <div style={{ ...PROBLEM, marginTop: "6px" }}>{error}</div>}
    </>
  );
}

/** What a summary line on a game's page opens, in place of the summary. */
type Choice = "game" | "emulator" | "system" | "discs" | "core";

/** A dropdown's options in one level, groups opened out. */
function flatOptions(options: DropdownOption[]): DropdownOption[] {
  return options.flatMap((option) => (option.options ? flatOptions(option.options) : [option]));
}

/** The label of the option holding `data`, for a summary line. */
function chosenLabel(options: DropdownOption[], data: unknown): React.ReactNode {
  return flatOptions(options).find((option) => option.data === data)?.label ?? "";
}

/** One summary line: what is set, and a way into changing it. */
function SummaryLine({ label, value, onClick, autoFocus = false }: {
  label: string;
  value: React.ReactNode;
  onClick: () => void;
  autoFocus?: boolean;
}) {
  return (
    <Focusable style={{ marginTop: "4px" }}>
      <DialogButton
        autoFocus={autoFocus}
        onClick={onClick}
        onOKActionDescription="Change"
        style={{ ...ICON_BUTTON_WIDE, justifyContent: "flex-start", width: "100%", gap: "10px" }}
      >
        <span style={{ flexShrink: 0, width: "90px", textAlign: "left" }}>{label}</span>
        <span style={{ flexGrow: 1, minWidth: 0, textAlign: "left", overflow: "hidden",
          textOverflow: "ellipsis", whiteSpace: "nowrap", opacity: 0.8 }}>{value}</span>
        <MdChevronRight aria-hidden style={{ flexShrink: 0, fontSize: "20px" }} />
      </DialogButton>
    </Focusable>
  );
}

/** A choice's options as a list, the current one marked. */
function OptionList({ options, selected, onPick }: {
  options: DropdownOption[];
  selected: unknown;
  onPick: (data: unknown) => void;
}) {
  return (
    <>
      {flatOptions(options).map((option, index, all) => (
        <Focusable key={String(option.data)} style={{ marginTop: "4px" }}>
          <DialogButton
            autoFocus={all.some((one) => one.data === selected) ? option.data === selected : index === 0}
            onClick={() => onPick(option.data)}
            onOKActionDescription="Choose"
            style={{ ...ICON_BUTTON_WIDE, justifyContent: "flex-start", width: "100%", gap: "10px" }}
          >
            <span style={{ width: "20px", flexShrink: 0 }}>
              {option.data === selected && <MdCheck aria-label="Chosen" />}
            </span>
            <span style={{ textAlign: "left" }}>{option.label}</span>
          </DialogButton>
        </Focusable>
      ))}
    </>
  );
}

/**
 * One game's page, shown in place of the list: its name, then one line for
 * each thing there is a choice about. A line opens its choice in the same
 * place, and B steps back out of it, so nothing opens on top of the review.
 */
function GamePage({ row, onBack, register }: {
  row: BatchRow;
  onBack: () => void;
  /** Hands the dialog this page's way back, for B. */
  register: (back: () => void) => void;
}) {
  const [name, setName] = useState(row.title);
  // What the field held before anyone typed, so a picked game can rename it.
  const [automatic, setAutomatic] = useState(row.title);
  const [everything, setEverything] = useState(false);
  const [choice, setChoice] = useState<Choice | null>(null);
  // The line a choice was opened from, focused again on the way back.
  const [from, setFrom] = useState<Choice | null>(null);
  const open = (next: Choice) => {
    setFrom(next);
    setChoice(next);
  };
  const [error, setError] = useState("");
  // Only for a core covering several systems, as in the panel.
  const systems = systemOptions(coreOf(row));
  const matching = row.probe?.matching_cores ?? [];
  const all = row.probe?.all_cores ?? [];
  const cores = everything || matching.length === 0 ? all : matching;
  const warnings = warningsOf(row);
  const discOptions = [
    { data: "one", label: `One game of ${row.discs.length} discs` },
    { data: "each", label: "Each disc on its own" },
  ];

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
    onBack();
  };
  const back = () => (choice ? setChoice(null) : done());
  register(back);
  const onClose = onBack;
  const picked = (apply: () => void) => {
    apply();
    setChoice(null);
  };

  if (choice) {
    const titles: Record<Choice, string> = {
      game: "Which game is this?", emulator: "Emulator", system: "System",
      discs: "Discs", core: "Core",
    };
    return (
      <>
        <div style={{ fontWeight: "bold", marginBottom: "4px" }}>{titles[choice]}</div>
        <ScrollList style={{ maxHeight: "40vh" }}>
          {choice === "game" && (
            <Candidates
              row={row}
              name={name}
              onPicked={(applied) => {
                const title = titleAfterArtPick(name, automatic, applied.suggested_title);
                setName(title);
                setAutomatic(title);
                setPickedGame(row.path, title, applied);
                setChoice(null);
              }}
            />
          )}
          {choice === "emulator" && (
            <>
              <OptionList options={coreOptions(cores)} selected={row.coreId}
                onPick={(data) => picked(() => void setRowCore(row.path, String(data)))} />
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
            </>
          )}
          {choice === "system" && (
            <OptionList options={systems} selected={row.systemId}
              onPick={(data) => picked(() => void setSystemFor(row.path, String(data)))} />
          )}
          {choice === "discs" && (
            <OptionList options={discOptions} selected={row.discMode}
              onPick={(data) => picked(() => setDiscMode(row.path, data === "each" ? "each" : "one"))} />
          )}
          {choice === "core" && (
            <OptionList options={installableOptions(row.installable)} selected={row.installableId}
              onPick={(data) => picked(() => setInstallable(row.path, String(data)))} />
          )}
        </ScrollList>
        <Focusable flow-children="row" style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
          <DialogButton onClick={back} style={{ flex: 1 }}>Back</DialogButton>
        </Focusable>
      </>
    );
  }

  const packaged = Boolean(row.probe?.ps4_package || row.probe?.vita_package || row.probe?.ps3_package);
  const gameName = withoutDiscTag(row.resolved?.art_game_name || row.resolved?.matched_name || "")
    || "Not identified";
  return (
    <>
      <Focusable style={{ display: "flex", gap: "12px", alignItems: "flex-start", marginBottom: "8px" }}>
        <Cover capsule={row.resolved?.art?.capsule?.data} width={64} />
        <div style={{ flexGrow: 1, minWidth: 0 }}>
          <TextField
            label="Name in Steam"
            value={name}
            bShowClearAction
            style={{ paddingRight: "2.6em" }}
            onChange={(event) => setName(event.target.value)}
          />
          <FileName name={rowFileLabel(row)} style={{ ...MUTED, marginTop: "6px" }} />
          {!row.fixed && row.resolved && NAME_SOURCE_LABELS[row.resolved.title_source] && (
            <div style={{ ...MUTED, marginTop: "2px" }}>{NAME_SOURCE_LABELS[row.resolved.title_source]}</div>
          )}
        </div>
      </Focusable>
      <ScrollList style={{ maxHeight: "none" }}>
        <SummaryLine label="Game" value={gameName} onClick={() => open("game")}
          autoFocus={(from ?? "game") === "game"} />
        {/* A file taken for the wrong platform usually needs another emulator,
            and the picker for its file type would change every such file. */}
        {/* A package names its own emulator. */}
        {all.length > 1 && !packaged && (
          <SummaryLine label="Emulator" value={coreName(row) || "None"} onClick={() => open("emulator")}
            autoFocus={from === "emulator"} />
        )}
        {systems.length > 0 && (
          <SummaryLine label="System" value={chosenLabel(systems, row.systemId)}
            onClick={() => open("system")} autoFocus={from === "system"} />
        )}
        {row.discs.length >= 2 && !discsMustSplit(row) && (
          <SummaryLine label="Discs" value={chosenLabel(discOptions, row.discMode)}
            onClick={() => open("discs")} autoFocus={from === "discs"} />
        )}
        {row.installable.length > 1 && row.verdict.step === "core" && (
          <SummaryLine label="Core" value={chosenLabel(installableOptions(row.installable), row.installableId)}
            onClick={() => open("core")} autoFocus={from === "core"} />
        )}

        {discsMustSplit(row) && (
          <ScrollRow>
            <div style={{ ...MUTED, marginTop: "10px" }}>
              {coreName(row) || "This emulator"} cannot be given a playlist, so each of
              the {row.discs.length} discs is added on its own, filed side by side.
            </div>
          </ScrollRow>
        )}
        {warnings.map((text) => (
          <ScrollRow key={text}>
            <div style={{ ...MUTED, marginTop: "10px" }}>{text}</div>
          </ScrollRow>
        ))}
        {error && <div style={{ ...PROBLEM, marginTop: "8px" }}>{error}</div>}

        <Focusable flow-children="row" style={{ display: "flex", gap: "8px", marginTop: "12px", flexWrap: "wrap" }}>
          {row.verdict.step === "retroarch" && <GetRetroArch />}
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
                onClose();
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
        </Focusable>
      </ScrollList>
      <Focusable flow-children="row" style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
        <DialogButton onClick={done} style={{ flex: 1 }}>Back</DialogButton>
      </Focusable>
    </>
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

/**
 * RetroArch, which Add cannot install: it comes from its own page, and the
 * review keeps meanwhile. Every other step Add does by itself.
 */
function GetRetroArch() {
  const press = () => {
    closeOpenModals();
    openManagePage("retroarch");
  };
  return <DialogButton onClick={press} style={{ flex: 1 }}>Get RetroArch</DialogButton>;
}

/** The row's file, or for a set the game and which discs are here. */
function rowFileLabel(row: BatchRow): string {
  return row.discs.length >= 2 ? discSetLabel(row.discs) : row.name;
}

function GameRow({ row, onEdit }: { row: BatchRow; onEdit: () => void }) {
  const capsule = row.resolved?.art?.capsule?.data;
  const stepping = row.busy && Boolean(row.stepStatus);
  const rest = [
    row.discs.length >= 2
      ? row.discMode === "each" || discsMustSplit(row)
        ? `${row.discs.length} discs, each on its own`
        : `${row.discs.length} discs as one game`
      : "",
    row.busy && !stepping ? "Looking up..." : row.verdict.reason,
    contentSummary(row),
    // Who supplies what the emulator is missing, said the same way for every
    // platform: what downloads by itself, and what has to be sent.
    row.needs.download.length ? `${row.needs.download.map((one) => one.name).join(", ")} downloads on Add` : "",
    sendFor(row).length ? `${sendFor(row).join(", ")} recommended` : "",
  ];
  return (
    <Focusable style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "4px" }}>
      {/* One size on every row: the column lines up and any cover can be checked. */}
      <Cover capsule={capsule} width={48} />
      <DialogButton
        onClick={() => setIncluded(row.path, !row.include)}
        onOKActionDescription={row.include ? "Untick" : "Tick"}
        // Not ready, and nothing Add can do about it: it cannot be ticked.
        disabled={row.busy || row.verdict.blocked}
        // Two lines, so the height follows the text, from the left.
        style={{ ...ICON_BUTTON_WIDE, height: "auto", minHeight: "48px", padding: "8px 16px",
          justifyContent: "flex-start", flexGrow: 1, minWidth: 0 }}
      >
        <div style={{ width: "100%", minWidth: 0 }}>
          <SwitchLabel name={row.title} on={row.include && !row.verdict.blocked} />
          {/* The file it came from, which is how a wrong match shows. One line,
              cut in the middle so the region tags and extension stay; the
              Fix dialog has it whole. */}
          <FileName name={rowFileLabel(row)} style={{ ...MUTED, marginLeft: "50px" }} />
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
      {/* The pencil Added games uses for editing a game; here it turns the
          dialog to this game's page. */}
      <DialogButton
        aria-label="Edit"
        onClick={onEdit}
        onOKActionDescription="Edit"
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
        <FileName name={rowFileLabel(row)} />
        <div style={MUTED}>
          {row.busy ? "Working..." : [row.verdict.reason, note].filter(Boolean).join(" · ")}
        </div>
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
          <FileName name={rowFileLabel(row)} />
          <div style={MUTED}>{row.busy ? "Checking again..." : row.verdict.reason}</div>
        </div>
      </div>
    </ScrollRow>
  );
}

function Review({ batch, hide, onEdit }: { batch: Batch; hide: () => void; onEdit: (path: string) => void }) {
  const choices = useMemo(() => coreChoices(batch.rows), [batch.rows]);
  const buckets: Bucket[] = ["ready", "check", "other", "cant"];
  const withGames = contentWithGames(batch.rows);
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
            <span style={{ opacity: 0.7 }}> ({count} game{count === 1 ? "" : "s"})</span>
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
          && !(row.verdict.other === "key" && withVitaPackage)
          // So does an update or DLC: its game's row counts it.
          && !(row.verdict.other === "content" && withGames.has(row.name)));
        if (!rows.length) return null;
        return (
          <div key={bucket}>
            <div style={{ ...MUTED, margin: "8px 0 4px" }}>
              {HEADINGS[bucket]} ({rows.length})
            </div>
            {rows.map((row) =>
              bucket === "other"
                ? <OtherRow key={row.path} row={row} hide={hide} />
                : bucket === "cant" ? <CantRow key={row.path} row={row} />
                  : <GameRow key={row.path} row={row} onEdit={() => onEdit(row.path)} />)}
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
  const stepping = rows.find((row) => row.busy && row.stepStatus);
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
  // The game whose page is showing in place of the list, if any. B on it goes
  // back to the list, keeping the name typed there.
  const [page, setPage] = useState("");
  const pageRow = phase === "review" ? rows.find((row) => row.path === page) : undefined;
  const pageBack = useRef<() => void>(() => setPage(""));
  const back = pageRow ? () => pageBack.current()
    : phase === "checking" || phase === "review" ? hide : close;

  return (
    <ModalRoot closeModal={phase === "adding" ? undefined : back} bAllowFullSize>
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "4px" }}>
        {phase === "done" ? "Added" : "Add games"}
      </div>

      {phase === "checking" && (
        <InstallProgress
          label={`Checking ${batch.done} of ${batch.total} file${batch.total === 1 ? "" : "s"}`}
          percent={batch.total ? Math.round((batch.done / batch.total) * 100) : 0}
          status=""
        />
      )}

      {pageRow && (
        <GamePage
          key={pageRow.path}
          row={pageRow}
          onBack={() => setPage("")}
          register={(done) => {
            pageBack.current = done;
          }}
        />
      )}

      {phase === "review" && !pageRow && (
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
          <Review batch={batch} hide={hide} onEdit={setPage} />
        </>
      )}

      {phase === "adding" && (
        <>
          <InstallProgress
            label={`Adding ${batch.current} (${Math.min(batch.done + 1, batch.total)} of ${batch.total})`}
            percent={batch.total ? Math.round((batch.done / batch.total) * 100) : 0}
            status=""
          />
          {/* A package or an emulator install takes minutes and reports how far
              it has got; the bar above only counts games. */}
          {stepping && (
            <div style={{ marginTop: "10px" }}>
              <InstallProgress inline label={stepping.stepStatus} percent={stepping.stepPercent} status="" />
            </div>
          )}
        </>
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
        </div>
      )}

      {/* Keyed by phase so its buttons mount anew and `autoFocus` takes. A
          game's page has its own Back in their place. */}
      {!pageRow && (
      <Focusable key={phase} flow-children="row" style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
        {phase === "review" && (
          <DialogButton autoFocus onClick={() => void addBatch()} disabled={busy || chosen.length === 0}>
            Add {chosen.length} game{chosen.length === 1 ? "" : "s"}
          </DialogButton>
        )}
        {phase !== "adding" && (
          <DialogButton
            // The Add button that had focus is gone; Close takes it.
            autoFocus={phase !== "review"}
            onClick={close}
          >
            {phase === "review" || phase === "checking" ? "Cancel" : "Close"}
          </DialogButton>
        )}
      </Focusable>
      )}
    </ModalRoot>
  );
}
