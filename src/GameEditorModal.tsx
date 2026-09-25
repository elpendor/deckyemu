import {
  ConfirmModal,
  DialogButton,
  Dropdown,
  Focusable,
  ModalRoot,
  Spinner,
  Tabs,
  TextField,
  type DropdownOption,
  type SingleDropdownOption,
} from "@decky/ui";
import { FileSelectionType, openFilePicker, toaster } from "@decky/api";
import { FaLink, FaTrash, FaUnlink } from "react-icons/fa";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  listWorkarounds,
  probeRom,
  gameIcon,
  resolveGame,
  addRomPatch,
  removeRomPatch,
  romPatches,
  switchRomPatch,
  syncRomPatches,
  type RomPatch,
  gameContent,
  installGameContent,
  removeGameContent,
  type GameContentRow,
  updateGame,
  type AddedGame,
  type Core,
  type GameOptions,
  type Workaround,
} from "./backend";
import {
  addAppsToCollection,
  applyArtwork,
  setShortcutIcon,
  renameShortcut,
  repointShortcut,
} from "./steam";
import { WorkaroundInfo } from "./WorkaroundInfo";
import { playGame } from "./playGame";
import { unfileGames } from "./collections";
import { ArtPickerModal } from "./ArtPickerModal";
import {
  coreOptions as buildCoreOptions,
  defaultSystem,
  isEmulatorId,
  coreLabel,
  pinnedLabel,
  systemOptions,
  withCurrentCore,
} from "./corePicker";
import { preselectCore } from "./CoreInstallPanel";
import { ScrollList } from "./ScrollList";
import { openManagePage } from "./manageRoute";
import { callWithRetry } from "./timeout";
import { logError } from "./logError";
import { sentence } from "./sentence";
import { filenameNamesTheGame } from "./lookupTerm";
import { titleAfterArtPick } from "./titleFromArt";
import { openModal } from "./modalStack";
import { DANGER_CLASS } from "./danger";
import { FileName } from "./FileName";
import { SwitchLabel } from "./SwitchLabel";
import { ICON_BUTTON, ICON_BUTTON_WIDE } from "./iconButton";

interface Props {
  game: AddedGame;
  onSaved: () => void;
  closeModal?: () => void;
  /**
   * Close whatever opened this, when leaving for another screen entirely.
   *
   * This modal is opened from the added-games list, which is itself a modal, so
   * closing only this one navigates to the setup page and leaves that list
   * stacked over it. A test launch is the same jump: Steam takes the screen and
   * the list would come back over the game. Not called on a plain save or on
   * cancel -- going back to the list is right then, and it is the only reason
   * the list is still open.
   */
  onLeave?: () => void;
}

const FIELD = { display: "flex", flexDirection: "column" as const, gap: "4px" };
/**
 * Field buttons span the modal, matching the text fields and dropdowns they sit
 * between. Sized to content they left a ragged right edge in a column of
 * full-width controls.
 */
const BUTTON = { width: "100%" };

/**
 * How tall the tab box is. The added games list uses 62vh with nothing under
 * its tabs; this editor has a footer of three buttons, so less. A starting
 * point to check on the device, not a measured answer.
 */
const EDITOR_TABS_HEIGHT = "50vh";

/**
 * A rule between the sections of a tab, and the class that draws it.
 *
 * Every section was a `<div>` in a 14px gap and nothing else, so a button and
 * the next section's label read as one block. The values are the ones
 * `EmulatorVersionModal` already uses between its rows.
 */
const PANE_CLASS = "deckyemu-editor-pane";

//: A caption for the whole tab, which the rule below must not sit under.
const PANE_NOTE_CLASS = "deckyemu-pane-note";

const PANE_CSS = `
.${PANE_CLASS} > * + * {
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  padding-top: 14px;
}
.${PANE_CLASS} > .${PANE_NOTE_CLASS} + * {
  border-top: none;
  padding-top: 0;
}
`;

/** "" means follow the global setting rather than override it. */
const OSD_OPTIONS: SingleDropdownOption[] = [
  { data: "", label: "Follow the global setting" },
  { data: "startup", label: "Hide the startup banner" },
  { data: "all", label: "Hide all on-screen messages" },
  { data: "keep", label: "Keep RetroArch's notifications" },
];

const FULLSCREEN_OPTIONS: SingleDropdownOption[] = [
  { data: "", label: "Follow the global setting" },
  { data: "on", label: "Force fullscreen" },
  { data: "off", label: "Leave windowed" },
];

/**
 * One workaround, as a choice this game makes, in one row: the fix's switch, a
 * link toggle for following the emulator, and the explanation.
 *
 * Three states -- follow the emulator, on, off -- from two controls that each
 * have two. "Follow" is the important state: a fix costs something for every
 * game its emulator runs, so a shortcut may differ from the default, but a game
 * that quietly stopped tracking that default would be found by nobody.
 *
 * * **Linked:** the switch is greyed out and shows the emulator's answer. It
 *   cannot be pressed, because there is nothing for this game to decide.
 * * **Unlinked:** the switch wakes up where it was -- the emulator's answer --
 *   and pressing it sets the fix for this game alone.
 *
 * The link's state is its shape, joined or broken, never its colour: a lit
 * button and a focused one are both drawn light, and the first version could not
 * be told apart from the cursor sitting on it.
 *
 * All three, always. Whether a fix is retired or cannot run changes what is said
 * about it, never which choices exist.
 */
function WorkaroundRow({
  fix,
  choice,
  onChoose,
}: {
  fix: Workaround;
  choice: string;
  onChoose: (value: string) => void;
}) {
  const following = choice === "";
  const on = following ? fix.enabled : choice === "on";

  return (
    <Focusable style={{ display: "flex", gap: "8px", alignItems: "center" }}>
      <DialogButton
        disabled={following}
        onClick={() => onChoose(on ? "off" : "on")}
        style={{ ...ICON_BUTTON_WIDE, flexGrow: 1 }}
      >
        <SwitchLabel name={fix.name} on={on} />
      </DialogButton>
      <DialogButton
        // Unlinking keeps what was showing, so the switch wakes up exactly
        // where it was and nothing changes until it is pressed.
        onClick={() => onChoose(following ? (fix.enabled ? "on" : "off") : "")}
        style={{ ...ICON_BUTTON, flexShrink: 0 }}
      >
        {following ? <FaLink /> : <FaUnlink />}
      </DialogButton>
      <WorkaroundInfo workaround={fix} />
    </Focusable>
  );
}

function basename(path: string): string {
  return path.slice(path.lastIndexOf("/") + 1) || path;
}

/**
 * The folder holding a tracked ROM, for the picker to open at.
 *
 * A tracked rom_path is always absolute, so the root is the only fallback needed
 * -- and it is correct everywhere, unlike a hardcoded /home/deck.
 */
function dirname(path: string): string {
  const cut = path.lastIndexOf("/");
  return cut > 0 ? path.slice(0, cut) : "/";
}

function Label({ children, hint }: { children: string; hint?: string }) {
  return (
    <div>
      <div style={{ fontSize: "14px", fontWeight: 500 }}>{children}</div>
      {hint && <div style={{ fontSize: "12px", opacity: 0.6 }}>{hint}</div>}
    </div>
  );
}

/**
 * Edit a game that is already in Steam.
 *
 * Without this, fixing a wrong name or a wrong artwork match means deleting the
 * shortcut and adding it again, which loses its playtime and its place in any
 * collection.
 *
 * Artwork is applied the moment it is chosen rather than on save: it needs no
 * launcher or collection work, and seeing the new capsule immediately is the
 * point of the picker. Everything else is written when Save is pressed.
 */
export function GameEditorModal({ game, onSaved, closeModal, onLeave }: Props) {
  const [title, setTitle] = useState(game.title);
  const [romPath, setRomPath] = useState(game.rom_path);
  const [coreId, setCoreId] = useState(game.core_id);
  const [cores, setCores] = useState<
    { matching: Core[]; all: Core[]; systemForCore: Record<string, string> } | null
  >(null);
  /**
   * Which of a multi-system core's systems this game is.
   *
   * Starts on where it is filed now, not on what the file says: this is the
   * record of a game that was already added, and showing anything else would
   * be quietly disagreeing with the shelf it is on. Changing it is the only
   * way to move a game filed under the wrong system -- the games added before
   * the add panel had a system row were filed by the artwork lookup, which put
   * Mega Drive games on the Game Gear shelf.
   */
  const [system, setSystem] = useState(game.system ?? "");
  const [showAll, setShowAll] = useState(false);
  type OsdChoice = NonNullable<GameOptions["hide_osd"]> | "";
  const [osd, setOsd] = useState<OsdChoice>(game.options?.hide_osd ?? "");
  const [fullscreen, setFullscreen] = useState(
    game.options?.fullscreen === undefined ? "" : game.options.fullscreen ? "on" : "off",
  );
  const [extraArgs, setExtraArgs] = useState(game.options?.extra_args ?? "");
  // The emulator's fixes, and this game's answer to each. Empty for every
  // emulator but the two with motion, and then nothing is rendered.
  const [fixes, setFixes] = useState<Workaround[]>([]);
  const [fixChoices, setFixChoices] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      Object.entries(game.options?.workarounds ?? {}).map(([id, on]) => [
        id,
        on ? "on" : "off",
      ]),
    ),
  );
  /**
   * The hacks on this game, in the order RetroArch applies them.
   *
   * Every change lands at once rather than waiting for Save, the way artwork
   * does: a list with a switch on each row that only takes effect later reads
   * as a list already in that state.
   */
  const [patches, setPatches] = useState<RomPatch[] | null>(null);
  const [patchWarning, setPatchWarning] = useState("");
  const [patchStart, setPatchStart] = useState("");
  const [patchBusy, setPatchBusy] = useState("");
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [artApplied, setArtApplied] = useState(0);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  // Opens on Game every time: unlike the added games list there is no place in
  // a browse worth coming back to.
  const [tab, setTab] = useState("game");

  useEffect(() => {
    let current = true;
    romPatches(game.app_id)
      .then((found) => {
        if (!current || !found.ok) return;
        setPatches(found.patches);
        setPatchWarning(found.warning);
        setPatchStart(found.start_in);
      })
      .catch((patchError) => {
        // Not surfaced: losing this list beats an error banner over an editor
        // somebody opened to rename a game.
        logError("could not read the ROM patches", patchError);
      });
    return () => {
      current = false;
    };
  }, [game.app_id]);

  /**
   * A Switch game's updates and DLC. `null` until read, and the section is only
   * drawn for an emulator that takes them -- Ryujinx, today.
   *
   * Changes land at once, like the patch list above: installing is a file move
   * and a rewrite of Ryujinx's list, not something Save would add to.
   */
  const [content, setContent] = useState<GameContentRow[] | null>(null);
  const [contentProblem, setContentProblem] = useState("");
  const [contentStart, setContentStart] = useState("");
  const [contentBusy, setContentBusy] = useState("");

  useEffect(() => {
    let current = true;
    gameContent(game.app_id)
      .then((found) => {
        if (!current || !found.ok || !found.supported) return;
        setContent(found.rows);
        setContentProblem(found.problem);
        setContentStart(found.start_in);
      })
      .catch((contentError) => {
        logError("could not read the game's updates and DLC", contentError);
      });
    return () => {
      current = false;
    };
  }, [game.app_id]);

  // Probing gives the same core ordering the add flow uses, so the sensible
  // choices come first here too. Re-runs when the ROM changes, because the new
  // file may well be for a different system.
  useEffect(() => {
    let current = true;
    setCores(null);
    callWithRetry(() => probeRom(romPath))
      .then((probe) => {
        if (!current) return;
        setCores({
          matching: probe.matching_cores,
          all: probe.all_cores,
          systemForCore: probe.system_for_core ?? {},
        });
        setShowAll(probe.matching_cores.length === 0);
      })
      .catch((probeError) => {
        if (!current) return;
        logError("could not probe ROM for editing", probeError);
        setError("Could not read that ROM, so the core list is unavailable.");
        setCores({ matching: [], all: [], systemForCore: {} });
      });
    return () => {
      current = false;
    };
  }, [romPath]);

  const visible = useMemo(() => {
    if (!cores) return [];
    const base = showAll || cores.matching.length === 0 ? cores.all : cores.matching;
    // The game's own core belongs in its own editor even when the filter would
    // drop it -- see withCurrentCore for the two ways that happens.
    return withCurrentCore(base, cores.all, coreId);
  }, [cores, showAll, coreId]);

  // Shared with the add panel rather than built again here: this list had
  // already drifted once, staying flat after the panel learned to separate
  // emulators from cores.
  const coreOptions: DropdownOption[] = useMemo(() => buildCoreOptions(visible), [visible]);

  const systemChoices: DropdownOption[] = useMemo(
    () => systemOptions(cores?.all.find((core) => core.id === coreId)),
    [cores, coreId],
  );

  /**
   * Follow the core: the answer only means anything against the core that
   * declared it.
   *
   * On the game's own core the stored answer stands, which is what makes the
   * row show where the game is filed. On any other, the file decides -- a
   * system carried over from the previous core would leave the row showing an
   * option it no longer has, and a `selectedOption` in no option draws nothing
   * at all.
   */
  useEffect(() => {
    if (!cores) return;
    const core = cores.all.find((candidate) => candidate.id === coreId);
    setSystem(
      defaultSystem(
        core,
        cores.systemForCore[coreId] ?? "",
        coreId === game.core_id ? game.system ?? "" : "",
      ),
    );
  }, [cores, coreId, game.core_id, game.system]);

  // Keyed on the core, so switching a game to a different emulator in this same
  // modal shows that emulator's fixes rather than the previous one's.
  useEffect(() => {
    const emulatorId = coreId.startsWith("emu:") ? coreId.slice(4) : "";
    if (!emulatorId) {
      setFixes([]);
      return;
    }
    let live = true;
    listWorkarounds(emulatorId)
      .then((result) => {
        if (live) setFixes(result.ok ? (result.workarounds ?? []) : []);
      })
      .catch(() => {
        if (live) setFixes([]);
      });
    return () => {
      live = false;
    };
  }, [coreId]);

  const isEmulator = isEmulatorId(coreId);

  // The core this game runs on is in no list, so it is not installed. Same
  // condition `pinnedLabel` reports on, kept as one expression so the label and
  // the button that answers it cannot disagree about whether it is missing.
  const missingCore = Boolean(cores) && Boolean(pinnedLabel(cores?.all ?? [], coreId));

  // Whether the file's name is the game's name. False for anything installed
  // from a package, which boots eboot.bin -- see lookupTerm.
  const byFilename = filenameNamesTheGame(romPath);

  const pickRom = useCallback(async () => {
    setError("");
    // openFilePicker rejects when the user backs out, so a cancel has to be told
    // apart from a real failure.
    let picked: { path: string; realpath: string } | undefined;
    try {
      picked = await openFilePicker(
        FileSelectionType.FILE,
        dirname(romPath),
        true,
        true,
        undefined,
        undefined,
        false,
        true,
      );
    } catch (pickError) {
      if (!String(pickError ?? "").toLowerCase().includes("cancel")) {
        logError("file picker failed", pickError);
        setError("Could not open the file browser.");
      }
      return;
    }

    // The picker's footer button submits the current *directory*, so a path
    // without a filename is a real possibility rather than an edge case.
    const path = picked?.realpath || picked?.path || "";
    if (!path) {
      setError("That selection did not return a file path.");
      return;
    }
    if (path === romPath) return;

    setRomPath(path);
    setNote("Check the core, and re-fetch the artwork if this is a different game.");
  }, [romPath]);

  /**
   * A refusal is a dialog, not the error line -- the same rule the updates list
   * below follows, for the same reason. That line is at the foot of this editor,
   * under everything scrolled past to reach the list, so a patch refused for
   * being the ROM read as a press that did nothing.
   */
  const showPatchRefusal = useCallback((heading: string, body: string) => {
    openModal(
      <ConfirmModal
        strTitle={heading}
        strDescription={body}
        strOKButtonText="Close"
        bAlertDialog
      />,
    );
  }, []);

  const afterPatchCall = useCallback(
    (result: Awaited<ReturnType<typeof addRomPatch>>, heading = "Not changed") => {
      if (result.patches) setPatches(result.patches);
      if (!result.ok) showPatchRefusal(heading, result.error || "Could not change the patches.");
      return result.ok;
    },
    [showPatchRefusal],
  );

  const togglePatch = useCallback(async (row: RomPatch) => {
    setPatchBusy(row.file);
    try {
      afterPatchCall(await switchRomPatch(game.app_id, row.file, !row.on));
    } catch (switchError) {
      logError("could not switch a patch", switchError);
      showPatchRefusal("Not changed", "Could not change that patch.");
    } finally {
      setPatchBusy("");
    }
  }, [game.app_id, afterPatchCall, showPatchRefusal]);

  const deletePatch = useCallback(async (row: RomPatch) => {
    setPatchBusy(row.file);
    try {
      afterPatchCall(await removeRomPatch(game.app_id, row.file), "Not removed");
    } catch (removeError) {
      logError("could not remove a patch", removeError);
      showPatchRefusal("Not removed", "Could not remove that patch.");
    } finally {
      setPatchBusy("");
    }
  }, [game.app_id, afterPatchCall, showPatchRefusal]);

  // Asked, like every other delete in the plugin. Our copy is the only one left
  // once a patch has been taken out of the transfer folder, so this is the
  // press that loses the file rather than one that can be undone by switching
  // it back on.
  const confirmDelete = useCallback(
    (row: RomPatch) => {
      openModal(
        <ConfirmModal
          strTitle={`Remove ${row.name}?`}
          strDescription="The copy this plugin keeps is deleted, so you would have to send the patch again to put it back. Your ROM file is not touched, and the game goes back to running unpatched."
          strOKButtonText="Remove"
          bDestructiveWarning
          onOK={() => void deletePatch(row)}
        />,
      );
    },
    [deletePatch],
  );

  // Opens on the transfer folder, which is where a patch sent from a phone
  // lands and the only place one is ever expected to be.
  const pickPatch = useCallback(async () => {
    let picked: { path: string; realpath: string } | undefined;
    try {
      picked = await openFilePicker(
        FileSelectionType.FILE,
        patchStart || dirname(romPath),
        true,
        true,
        undefined,
        undefined,
        false,
        true,
      );
    } catch (pickError) {
      if (!String(pickError ?? "").toLowerCase().includes("cancel")) {
        logError("patch picker failed", pickError);
        showPatchRefusal("Not installed", "Could not open the file browser.");
      }
      return;
    }
    const path = picked?.realpath || picked?.path || "";
    if (!path) {
      showPatchRefusal("Not installed", "That selection did not return a file path.");
      return;
    }
    setPatchBusy(path);
    try {
      afterPatchCall(await addRomPatch(game.app_id, path), "Not installed");
    } catch (addError) {
      logError("could not add a patch", addError);
      showPatchRefusal("Not installed", "Could not install that patch.");
    } finally {
      setPatchBusy("");
    }
  }, [romPath, patchStart, game.app_id, afterPatchCall, showPatchRefusal]);

  /**
   * A refusal is a dialog, not the error line.
   *
   * That line sits at the foot of this editor, below everything the user
   * scrolled past to reach the list -- so an update for another game was
   * refused with a correct sentence nobody could see, and the press looked like
   * it did nothing at all.
   */
  const showContentRefusal = useCallback((heading: string, body: string) => {
    openModal(
      <ConfirmModal
        strTitle={heading}
        strDescription={body}
        strOKButtonText="Close"
        bAlertDialog
      />,
    );
  }, []);

  const afterContentCall = useCallback(
    (result: Awaited<ReturnType<typeof installGameContent>>, heading: string) => {
      if (result.rows) setContent(result.rows);
      if (!result.ok) {
        showContentRefusal(heading, result.error || "Could not change the updates and DLC.");
      }
    },
    [showContentRefusal],
  );

  const deleteContent = useCallback(async (row: GameContentRow) => {
    setContentBusy(row.file);
    try {
      afterContentCall(await removeGameContent(game.app_id, row.file), "Not removed");
    } catch (removeError) {
      logError("could not remove an update or DLC", removeError);
      showContentRefusal("Not removed", "Could not remove that file.");
    } finally {
      setContentBusy("");
    }
  }, [game.app_id, afterContentCall, showContentRefusal]);

  // Asked, like the patch bin above. The copy kept here is usually the only one
  // left on the Deck, and an update is gigabytes to send again.
  const confirmDeleteContent = useCallback(
    (row: GameContentRow) => {
      openModal(
        <ConfirmModal
          strTitle={`Remove ${row.label}?`}
          strDescription={
            row.kind === "update"
              ? "The file is deleted from this Deck, so you would have to send it again to put it back. The game runs the update before it, or none."
              : "The file is deleted from this Deck, so you would have to send it again to put it back. The game runs without it."
          }
          strOKButtonText="Remove"
          bDestructiveWarning
          onOK={() => void deleteContent(row)}
        />,
      );
    },
    [deleteContent],
  );

  // Opens on the transfer folder, where an update sent from another device lands.
  const pickContent = useCallback(async () => {
    let picked: { path: string; realpath: string } | undefined;
    try {
      picked = await openFilePicker(
        FileSelectionType.FILE,
        contentStart || dirname(romPath),
        true,
        true,
        undefined,
        undefined,
        false,
        true,
      );
    } catch (pickError) {
      if (!String(pickError ?? "").toLowerCase().includes("cancel")) {
        logError("update picker failed", pickError);
        showContentRefusal("Not installed", "Could not open the file browser.");
      }
      return;
    }
    const path = picked?.realpath || picked?.path || "";
    if (!path) {
      showContentRefusal("Not installed", "That selection did not return a file path.");
      return;
    }
    setContentBusy(path);
    try {
      afterContentCall(await installGameContent(game.app_id, path), "Not installed");
    } catch (installError) {
      logError("could not install an update or DLC", installError);
      showContentRefusal("Not installed", "Could not install that file.");
    } finally {
      setContentBusy("");
    }
  }, [romPath, contentStart, game.app_id, afterContentCall, showContentRefusal]);

  /**
   * Take the icon out of artwork that just arrived, if it brought one.
   *
   * **Only when there is one.** Asking for the icon with nothing to give would
   * answer with the shipped picture, which would quietly replace real artwork
   * on a game that already had it -- picking a libretro thumbnail fetches a
   * capsule and nothing else, so that is not a rare case.
   */
  const applyIcon = useCallback(async (art?: { icon?: { data: string } }) => {
    const data = art?.icon?.data;
    if (!data) return;
    try {
      const found = await gameIcon(game.app_id, data);
      if (found.path) setShortcutIcon(game.app_id, found.path);
    } catch (iconError) {
      logError("could not set the icon from the artwork", iconError);
    }
  }, [game.app_id]);

  const pickArtwork = useCallback(() => {
    openModal(
      <ArtPickerModal
        romPath={romPath}
        coreId={coreId}
        // The name to open on, when the filename is not one.
        initialQuery={byFilename ? "" : title.trim()}
        onApplied={(result) => {
          void (async () => {
            try {
              const applied = await applyArtwork(game.app_id, result.art);
              await applyIcon(result.art);
              setArtApplied(applied);

              // And the name, by the same rule the add flow uses -- see
              // titleFromArt.ts. The shortcut is renamed on Save, like every
              // other edit here; artwork applies immediately because it needs
              // nothing else to happen first.
              const nextTitle = titleAfterArtPick(title, game.title, result.suggested_title);
              if (nextTitle !== title) {
                setTitle(nextTitle);
                setNote("Name taken from the artwork you picked. Save to apply it.");
              } else {
                // Picking a game and watching only the artwork change is the
                // shape of two separate faults -- an empty suggestion, or a
                // name the rule declined to overwrite -- and from the outside
                // they look identical. Neither is an error, so nothing was
                // written down and the report of it could not be diagnosed.
                logError(
                  "art pick left the name alone",
                  "",
                  `suggested=${JSON.stringify(result.suggested_title)} ` +
                    `current=${JSON.stringify(title)} ` +
                    `automatic=${JSON.stringify(game.title)}`,
                );
              }

              toaster.toast({
                title: applied > 0 ? "Artwork updated" : "Artwork could not be applied",
                body: result.art_game_name || `${applied} image(s)`,
              });
            } catch (error) {
              // Everything above ran unguarded, so a throw anywhere in it left
              // the artwork applied, the name unchanged, and no toast -- which
              // is precisely the symptom being chased, reported as silence.
              logError("could not finish applying the picked game", error);
              toaster.toast({
                title: "Artwork could not be applied",
                body: "Something went wrong applying that game.",
              });
            }
          })();
        }}
      />,
    );
    // `title` is in here because the rule above reads it. Without it the
    // callback keeps the name the field had when the editor opened, so typing
    // a name and *then* picking a game threw the typed name away -- the one
    // case the rule exists to protect.
  }, [romPath, game.app_id, coreId, game.title, title, byFilename, applyIcon]);

  /**
   * Re-run the normal name and artwork lookup for the current core.
   *
   * Worth its own button because the core decides the system, and the system
   * decides which libretro thumbnail directory is searched -- so art that could
   * not be found before a core change may resolve straight away after one.
   */
  const refetch = useCallback(async () => {
    setRefreshing(true);
    setError("");
    try {
      // The name when the file cannot supply one -- otherwise every game
      // installed from a package looks itself up as "Eboot".
      const resolved = await resolveGame(
        romPath,
        coreId,
        byFilename ? "" : title.trim(),
        // The system decides which thumbnail directory is searched first, so
        // this is what stops a Mega Drive game being handed a Game Gear cover.
        system,
      );
      const applied = await applyArtwork(game.app_id, resolved.art);
      // Where an old game gets a real icon: the lookup already fetched one if
      // SteamGridDB had it, so this costs nothing more.
      await applyIcon(resolved.art);
      setArtApplied(applied);
      if (resolved.title) setTitle(resolved.title);
      toaster.toast({
        title: resolved.title || game.title,
        body:
          applied > 0
            ? `${applied} image(s) from ${resolved.art_source}${
                resolved.art_game_name ? ` (${resolved.art_game_name})` : ""
              }`
            : "No artwork found for this system.",
      });
    } catch (refetchError) {
      logError("could not re-fetch metadata", refetchError);
      setError("Could not look that game up again.");
    } finally {
      setRefreshing(false);
    }
    // `title` and not only `game.title`, for the reason spelled out on
    // `pickRom` above: `game.title` is the name the editor opened with, and
    // `title` is what is in the field now. Without it this button looked the
    // game up under the old name after somebody typed a new one -- the same
    // fault `pickRom` was fixed for, in the callback beside it, left behind
    // because the fix was made by hand and this array was not read again.
  }, [romPath, coreId, system, game.app_id, game.title, title, byFilename,
      applyIcon]);

  const currentOptions = useCallback((): GameOptions => {
    const options: GameOptions = {};
    if (osd) options.hide_osd = osd as GameOptions["hide_osd"];
    if (fullscreen) options.fullscreen = fullscreen === "on";
    if (extraArgs.trim()) options.extra_args = extraArgs.trim();
    // Only the ones this game actually decides. "Follow the emulator" is the
    // absence of an entry, not a third value to store.
    const decided = Object.entries(fixChoices).filter(([, choice]) => choice);
    if (decided.length > 0) {
      options.workarounds = Object.fromEntries(
        decided.map(([id, choice]) => [id, choice === "on"]),
      );
    }
    return options;
  }, [osd, fullscreen, extraArgs, fixChoices]);

  /**
   * Write the changes, and report whether they landed.
   *
   * The answer is for the test launch: a failed save leaves this modal open
   * showing why, and starting the game on top of that would run the settings
   * the user was trying to change.
   */
  const save = useCallback(async (): Promise<boolean> => {
    setSaving(true);
    setError("");
    try {
      const result = await updateGame(
        game.app_id, title, coreId, romPath, currentOptions(), system,
      );
      if (!result.ok) {
        setError(result.error);
        return false;
      }

      const notes: string[] = [];

      if (result.title !== game.title) {
        // Steam may not refresh an already-visible entry at once, so a stale
        // name in the library is not treated as a failure.
        renameShortcut(game.app_id, result.title);
        notes.push("renamed");
      }

      // Only when the launcher moved: the filename embeds the title and a hash
      // of the ROM path, so either change relocates it.
      if (result.launcher_changed) {
        repointShortcut(game.app_id, result.exe);
      }

      if (result.collection !== result.previous_collection) {
        // Added before removed, so the game is never briefly on no shelf at
        // all. `unfileGames` does the removal, which is also what gives back
        // the old collection if this emptied it -- editing the last game on a
        // shelf is one of the ways one is left standing with nothing on it.
        if (result.collection) await addAppsToCollection(result.collection, [game.app_id]);
        await unfileGames([
          { app_id: game.app_id, collection: result.previous_collection },
        ]);
        notes.push(`moved to ${result.collection || "no collection"}`);
      }

      if (result.rom_changed) notes.push(`now runs ${basename(result.rom_path)}`);

      // The patch files are named after the ROM, so pointing the game at
      // another one leaves them beside a file nothing loads. Written again
      // after the update rather than before, so they land beside the new one.
      if (result.rom_changed && patches?.some((one) => one.on)) {
        const moved = await syncRomPatches(game.app_id);
        if (!moved.ok) {
          setError(moved.error || "Could not move the patches to the new ROM.");
          return false;
        }
      }
      if (coreId !== game.core_id) {
        // Both, and the core first: this note exists *because* the core
        // changed, and it used to report only the platform -- which is the
        // thing that usually does not change when you switch core, so
        // swapping snes9x for bsnes said "now runs on Super Nintendo".
        const label = coreLabel(cores?.all ?? [], coreId);
        notes.push(
          label
            ? `now runs on ${label} (${result.platform})`
            : `now runs on ${result.platform}`,
        );
      }
      else if (system !== game.system) notes.push(`filed as ${result.platform}`);

      toaster.toast({
        title: result.title,
        // Each note reads correctly in the middle of a list and wrongly at the
        // front of one, and only the join knows which it ended up as.
        body: notes.length ? sentence(notes.join(", ")) : "Saved.",
      });
      onSaved();
      closeModal?.();
      return true;
    } catch (saveError) {
      logError("could not save game", saveError);
      setError("Could not save those changes.");
      return false;
    } finally {
      setSaving(false);
    }
    // `cores?.all` because the toast names what the game now runs on, and a
    // stale list would name the core it ran on before.
  }, [game, title, coreId, system, romPath, patches, currentOptions, onSaved,
      closeModal, cores?.all]);

  /**
   * Launch the game to check the change worked.
   *
   * Saves first: the launcher on disk is what Steam runs, so testing before
   * writing it would test the old settings. Nothing is launched if that save
   * failed -- the error is on screen here, and the game would run the old
   * settings anyway.
   *
   * Every modal closes before the launch, this one and the list that opened it
   * -- see `playGame` for why that ordering is not cosmetic.
   */
  const testLaunch = useCallback(async () => {
    if (!(await save())) return;
    // `save` closed this modal; `playGame` closes the list that opened it --
    // unless something else is running, in which case it asks first and the
    // list is what its Cancel goes back to. The edited title, not the stored
    // one: the save above is what just made it the game's name.
    playGame(game.app_id, title.trim(), onLeave);
  }, [save, game.app_id, title, onLeave]);

  // Counts an unsaved choice, so the row does not offer "choose" for a file it
  // is already showing.
  const patchHint = [
    patches?.length
      ? "Applied in this order as the game loads. Your ROM file is never changed."
      : "None yet. Send a patch through the transfer page, then install it here or from its row there. Your ROM file is never changed.",
    patchWarning,
  ]
    .filter(Boolean)
    .join(" ");

  const coreChanged = coreId !== game.core_id;
  const busy = saving || refreshing;

  // Each tab's content, scrolled the way every other list here scrolls. Steam's
  // own pane must stay still -- letting it do the scrolling turned the tab bar
  // black as content moved under it.
  //
  // `ScrollList` rather than the `overflowY` pair this used to write itself:
  // that is three quarters of a scroll region, and the missing quarter is the
  // scrollbar, which Steam's CEF draws for nobody. Without it there is nothing
  // saying the tab continues below the fold -- and the footer sits right under
  // it, so what is content and what is the end of the dialog read the same.
  const pane = (children: React.ReactNode) => (
    <>
      <style>{PANE_CSS}</style>
      <ScrollList
        className={PANE_CLASS}
        style={{
          gap: "14px",
          height: "100%",
          boxSizing: "border-box",
          paddingTop: "8px",
          paddingBottom: "8px",
        }}
      >
        {children}
      </ScrollList>
    </>
  );

  const nameAndArtwork = (
    <div style={FIELD}>
      <Label
        hint={
          artApplied > 0
            ? `${artApplied} image(s) applied. Artwork lands immediately; a name change waits for Save.`
            : `Artwork lands immediately, a name change waits for Save. Looking up by ${
                byFilename ? "filename" : "name"
              } also uses the current core, which decides where boxart comes from.`
        }
      >
        Name and artwork
      </Label>
      <div style={FIELD}>
        <DialogButton onClick={pickArtwork} style={BUTTON} disabled={busy}>
          Choose the right game
        </DialogButton>
        {/* Named after what it looks the game up *by*: one takes the game you
            point at, the other takes the file's name and guesses, and only this
            one replaces a name you typed. "by name" when the file has none of
            its own -- a package boots eboot.bin, and "by filename" would be a
            search for "Eboot". */}
        <DialogButton onClick={() => void refetch()} style={BUTTON} disabled={busy}>
          {refreshing
            ? "Looking up..."
            : byFilename
              ? "Look up by filename"
              : "Look up by name"}
        </DialogButton>
      </div>
    </div>
  );

  const runningTab = pane(
    <>
      <div style={FIELD}>
        <Label
          hint={
            coreChanged
              ? "Changing this rewrites the launcher and may move the game to another collection."
              : `Currently ${game.platform || game.system || "unknown system"}.`
          }
        >
          Core or emulator
        </Label>
        {!cores ? (
          <Spinner style={{ height: "20px" }} />
        ) : (
          <Dropdown
            rgOptions={coreOptions}
            selectedOption={coreId}
            // Shown only when nothing is selected, which here means the core
            // this game runs on is no longer installed. Without it the control
            // is simply blank, which reads as the editor being broken.
            strDefaultLabel={pinnedLabel(cores.all, coreId) || undefined}
            onChange={(option) => setCoreId(String(option.data))}
          />
        )}
        {cores && cores.matching.length > 0 && (
          <DialogButton onClick={() => setShowAll((previous) => !previous)} style={BUTTON}>
            {showAll ? "Show matching only" : "Show everything installed"}
          </DialogButton>
        )}

        {/* The core this game runs on is gone. Sends the user to the tab that
            installs one, with this core already chosen, rather than installing
            it here: a second place that installs cores is duplication that has
            drifted twice before. */}
        {cores && missingCore && (
          <DialogButton
            style={BUTTON}
            onClick={() => {
              // Modals first, navigation last: `openManagePage` closes the Quick
              // Access panel, and Steam re-reveals it as each modal above it
              // dismisses.
              closeModal?.();
              onLeave?.();
              if (isEmulator) {
                openManagePage("emulators");
              } else {
                preselectCore(coreId);
                openManagePage("retroarch");
              }
            }}
          >
            {isEmulator ? "Set up this emulator" : "Install this core"}
          </DialogButton>
        )}
      </div>

      {/* Only for a core covering several systems. This is where a game filed
          under the wrong one gets moved -- deleting and re-adding produced the
          same wrong answer. */}
      {systemChoices.length > 0 && (
        <div style={FIELD}>
          <Label
            hint={
              system === game.system
                ? "Which shelf this game belongs on, and where its artwork comes from."
                : "Saving moves the game to the collection for this system."
            }
          >
            System
          </Label>
          <Dropdown
            rgOptions={systemChoices}
            selectedOption={system}
            onChange={(option) => setSystem(String(option.data))}
          />
        </div>
      )}

      <div style={FIELD}>
        <Label hint="Overrides Settings for this one game. Leave on 'follow' to keep tracking it.">
          Launch options
        </Label>
        {isEmulator ? (
          <Dropdown
            rgOptions={FULLSCREEN_OPTIONS}
            selectedOption={fullscreen}
            onChange={(option) => setFullscreen(String(option.data))}
          />
        ) : (
          <Dropdown
            rgOptions={OSD_OPTIONS}
            selectedOption={osd}
            onChange={(option) => setOsd(String(option.data) as OsdChoice)}
          />
        )}
        <TextField
          label="Extra arguments"
          value={extraArgs}
          onChange={(event) => setExtraArgs(event.target.value)}
        />
        <div style={{ fontSize: "12px", opacity: 0.6 }}>
          Appended to the command line and split like a shell would. Some emulators expect
          the ROM last and will ignore anything after it.
        </div>
      </div>

      {fixes.length > 0 && (
        <div style={FIELD}>
          <Label hint="While linked, the game uses the emulator's setting.">Fixes</Label>
          {fixes.map((fix) => (
            <WorkaroundRow
              key={fix.id}
              fix={fix}
              choice={fixChoices[fix.id] ?? ""}
              onChoose={(value) =>
                setFixChoices((current) => ({ ...current, [fix.id]: value }))
              }
            />
          ))}
        </div>
      )}
    </>,
  );

  const addonsTab = pane(
    <>
      <div className={PANE_NOTE_CLASS} style={{ fontSize: "12px", opacity: 0.6 }}>
        Changes on this tab apply straight away, without Save.
      </div>

      {/* RetroArch only: a standalone emulator ignores a file beside a ROM, so
          the list there would promise something that never happens. */}
      {!isEmulator && (
        <div style={FIELD}>
          <Label hint={patchHint}>ROM hacks</Label>
          {(patches ?? []).map((row) => (
            <Focusable
              key={row.file}
              style={{ display: "flex", gap: "8px", alignItems: "center" }}
            >
              {/* The same shape as the emulator editor's fixes: a wide button
                  that is the switch, and a small one beside it. */}
              <DialogButton
                onClick={() => void togglePatch(row)}
                style={{ ...ICON_BUTTON_WIDE, flexGrow: 1 }}
                disabled={busy || patchBusy === row.file}
              >
                {patchBusy === row.file ? (
                  "Working..."
                ) : (
                  <SwitchLabel name={row.name} on={row.on} />
                )}
              </DialogButton>
              {/* `flexShrink` because the row is flex and the square would
                  otherwise be squeezed by a long patch name. */}
              <div className={DANGER_CLASS} style={{ flexShrink: 0 }}>
                <DialogButton
                  onClick={() => confirmDelete(row)}
                  style={ICON_BUTTON}
                  disabled={busy || patchBusy === row.file}
                >
                  <FaTrash />
                </DialogButton>
              </div>
            </Focusable>
          ))}
          <DialogButton
            onClick={() => void pickPatch()}
            style={BUTTON}
            disabled={busy || Boolean(patchBusy)}
          >
            Install a patch
          </DialogButton>
        </div>
      )}

      {content !== null && (
        <div style={FIELD}>
          <Label
            hint={
              contentProblem ||
              (content.length
                ? "Ryujinx runs the newest update and every DLC as the game starts."
                : "None yet. Send an update or DLC through the transfer page, then install it here.")
            }
          >
            Updates and DLC
          </Label>
          {content.map((row) => (
            <Focusable
              key={row.file}
              style={{ display: "flex", gap: "8px", alignItems: "center" }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div>
                  {contentBusy === row.file
                    ? "Working..."
                    : row.used
                      ? row.label
                      : `${row.label} — not used, a newer update is`}
                </div>
                <FileName name={row.file} style={{ fontSize: "12px", opacity: 0.7 }} />
              </div>
              <div className={DANGER_CLASS} style={{ flexShrink: 0 }}>
                <DialogButton
                  onClick={() => confirmDeleteContent(row)}
                  style={ICON_BUTTON}
                  disabled={busy || Boolean(contentBusy)}
                >
                  <FaTrash />
                </DialogButton>
              </div>
            </Focusable>
          ))}
          <DialogButton
            onClick={() => void pickContent()}
            style={BUTTON}
            disabled={busy || Boolean(contentBusy) || Boolean(contentProblem)}
          >
            {contentBusy && !content.some((row) => row.file === contentBusy)
              ? "Installing..."
              : "Install an update or DLC"}
          </DialogButton>
        </div>
      )}

      {/* Always a tab, even with nothing on it: tabs that come and go move
          where the bumpers land, and changing the core on Running would add or
          remove one mid-edit. */}
      {isEmulator && content === null && (
        <div style={{ fontSize: "13px", opacity: 0.8 }}>
          Nothing to add for games on this emulator. ROM hacks work with RetroArch
          games, and updates and DLC with Ryujinx.
        </div>
      )}
    </>,
  );

  const gameTab = pane(
    <>
      <div style={FIELD}>
        <Label hint="The name shown in your Steam library.">Name</Label>
        <TextField value={title} onChange={(event) => setTitle(event.target.value)} />
      </div>

      {nameAndArtwork}

      <div style={FIELD}>
        <Label hint={romPath === game.rom_path ? basename(romPath) : `New file: ${basename(romPath)}`}>
          ROM file
        </Label>
        <DialogButton onClick={() => void pickRom()} style={BUTTON} disabled={busy}>
          Change ROM file
        </DialogButton>
      </div>

    </>,
  );

  return (
    <ModalRoot closeModal={closeModal} bAllowFullSize>
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "4px" }}>
        Edit {game.title}
      </div>

      {/* A stated height, for the reason the added games list gives: Steam's
          tab row fills a sized parent and a modal sizes to its content, so
          without one the tabs render below the dialog's border. `overflow:
          hidden` clips the slide Steam animates between panes. What is left of
          the panel after the title and the footer is roughly this. */}
      {/* Steam's pane pads itself 58px top, 24px sides and 40px bottom, measured
          on the device. The top keeps content clear of the tab row and stays;
          the sides and bottom only inset this editor inside its own dialog, so
          they go. `_TabContentsScroll` is one of Steam's unhashed class names. */}
      <style>{`.deckyemu-editor-tabs ._TabContentsScroll { padding-left: 0; padding-right: 0; padding-bottom: 0; }`}</style>
      <div
        className="deckyemu-editor-tabs"
        style={{
          height: EDITOR_TABS_HEIGHT,
          display: "flex",
          flexDirection: "column",
          // `clip`, not `hidden`. Both cut off the panes Steam slides in from
          // beyond the edges, but a `hidden` box can still be scrolled by code:
          // pressing a bumper with focus inside a tab moved focus into the
          // incoming pane, Steam's smooth focus scroll scrolled this box up to
          // 243px sideways to reach it, and the tab bar slid with the content.
          // Recorded frame by frame on the device. A `clip` box is not a scroll
          // container, so there is nothing for that scroll to move.
          overflow: "clip",
          // Where the tabs end and the dialog's own buttons begin. On the box
          // rather than on the footer, so the line does not move when a note or
          // an error appears between them.
          //
          // Twice the width and three times the contrast of the rules between
          // sections. At the same weight the two read as the same kind of line
          // and the boundary said nothing: the question is not "is there a
          // line" but "is this one the end of the content".
          borderBottom: "2px solid rgba(255, 255, 255, 0.3)",
        }}
      >
        <Tabs
          activeTab={tab}
          onShowTab={(next: string) => setTab(next)}
          tabs={[
            { id: "game", title: "Game", content: gameTab },
            { id: "emulator", title: "Emulator", content: runningTab },
            { id: "addons", title: "Add-ons", content: addonsTab },
          ]}
        />
      </div>

      {note && (
        <div style={{ fontSize: "13px", opacity: 0.8, marginTop: "6px" }}>{note}</div>
      )}
      {error && (
        <div style={{ color: "#e35d5d", fontSize: "13px", marginTop: "6px" }}>{error}</div>
      )}

      {/* Outside the tabs, so Save is visibly for the whole editor. One row that
          does not wrap: a Steam button claims a full line whenever its row lets
          it, and three stacked buttons under a fixed-height tab box ran off the
          bottom of the panel. */}
      <Focusable style={{ display: "flex", gap: "8px", marginTop: "14px" }}>
        <DialogButton
          onClick={() => void save()}
          disabled={busy || !title.trim()}
          style={{ flex: 1, minWidth: 0 }}
        >
          {saving ? "Saving..." : "Save"}
        </DialogButton>
        <DialogButton
          onClick={() => void testLaunch()}
          disabled={busy || !title.trim()}
          style={{ flex: 1, minWidth: 0 }}
        >
          Save and test
        </DialogButton>
        <DialogButton
          onClick={() => closeModal?.()}
          disabled={busy}
          style={{ flex: 1, minWidth: 0 }}
        >
          Close
        </DialogButton>
      </Focusable>
    </ModalRoot>
  );
}
