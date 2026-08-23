import {
  DialogButton,
  Dropdown,
  Focusable,
  ModalRoot,
  Spinner,
  TextField,
  type DropdownOption,
  type SingleDropdownOption,
} from "@decky/ui";
import { FileSelectionType, openFilePicker, toaster } from "@decky/api";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  probeRom,
  resolveGame,
  updateGame,
  type AddedGame,
  type Core,
  type GameOptions,
} from "./backend";
import {
  addAppsToCollection,
  applyArtwork,
  renameShortcut,
  repointShortcut,
} from "./steam";
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
import { openManagePage } from "./manageRoute";
import { callWithRetry } from "./timeout";
import { logError } from "./logError";
import { sentence } from "./sentence";
import { filenameNamesTheGame } from "./lookupTerm";
import { titleAfterArtPick } from "./titleFromArt";
import { openModal } from "./modalStack";

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
const ROW = { display: "flex", gap: "8px", flexWrap: "wrap" as const };
/**
 * Field buttons span the modal, matching the text fields and dropdowns they sit
 * between. Sized to content they left a ragged right edge in a column of
 * full-width controls.
 */
const BUTTON = { width: "100%" };

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
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [artApplied, setArtApplied] = useState(0);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

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
  }, [romPath, game.app_id, coreId, game.title, title, byFilename]);

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
  }, [romPath, coreId, system, game.app_id, game.title, title, byFilename]);

  const currentOptions = useCallback((): GameOptions => {
    const options: GameOptions = {};
    if (osd) options.hide_osd = osd as GameOptions["hide_osd"];
    if (fullscreen) options.fullscreen = fullscreen === "on";
    if (extraArgs.trim()) options.extra_args = extraArgs.trim();
    return options;
  }, [osd, fullscreen, extraArgs]);

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
  }, [game, title, coreId, system, romPath, currentOptions, onSaved, closeModal,
      cores?.all]);

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

  const coreChanged = coreId !== game.core_id;
  const busy = saving || refreshing;

  return (
    <ModalRoot closeModal={closeModal} bAllowFullSize>
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "12px" }}>
        Edit {game.title}
      </div>

      <Focusable style={{ ...FIELD, gap: "14px" }}>
        <div style={FIELD}>
          <Label hint="The name shown in your Steam library.">Name</Label>
          <TextField value={title} onChange={(event) => setTitle(event.target.value)} />
        </div>

        <div style={FIELD}>
          <Label hint={romPath === game.rom_path ? basename(romPath) : `New file: ${basename(romPath)}`}>
            ROM file
          </Label>
          <DialogButton onClick={() => void pickRom()} style={BUTTON} disabled={busy}>
            Change ROM file
          </DialogButton>
        </div>

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
              // this game runs on is no longer installed. Without it the
              // control is simply blank, which reads as the editor being
              // broken rather than as the core having been removed.
              strDefaultLabel={pinnedLabel(cores.all, coreId) || undefined}
              onChange={(option) => setCoreId(String(option.data))}
            />
          )}
          {cores && cores.matching.length > 0 && (
            <DialogButton onClick={() => setShowAll((previous) => !previous)} style={BUTTON}>
              {showAll ? "Show matching only" : "Show everything installed"}
            </DialogButton>
          )}

          {/* The core this game runs on is gone -- uninstalling RetroArch takes
              its cores with it. Sends the user to the tab that installs one,
              with this core already chosen, rather than installing it here:
              that tab already handles RetroArch being absent too, and a second
              place that installs cores is the duplication this project has
              twice watched drift. One tap instead of six navigations. */}
          {cores && missingCore && (
            <DialogButton
              style={BUTTON}
              onClick={() => {
                // Modals first, navigation last, and the order is the whole of
                // it: `openManagePage` closes the Quick Access panel on its way
                // out, and Steam re-reveals that panel as each modal above it
                // dismisses. Navigating first meant arriving at the page with
                // the panel open again over it.
                closeModal?.();
                // The list this was opened from, which would otherwise be left
                // sitting over the page just navigated to.
                onLeave?.();

                if (isEmulator) {
                  // Not a libretro core, so the core list cannot install it.
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
            under the wrong one gets moved: everything added before the add
            panel gained the same row had its system inferred from whichever
            system's cover art matched the filename first, which put Mega Drive
            games on the Game Gear shelf. Deleting and re-adding was the only
            way back, and it produced the same answer. */}
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
          <Label
            hint={
              artApplied > 0
                // This used to warn that a game page open behind the editor
                // would sit blank until it was re-opened, which it did: applying
                // emptied all four slots before writing any, and a details page
                // renders that gap. It does not any more -- `steam/artwork.ts`
                // clears each slot immediately before its own write -- so the
                // warning is gone rather than reworded.
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
            {/* Named after what it looks the game up *by*, because that is the
                whole difference between these two buttons: one takes the game
                you point at, the other takes the file's name and guesses. Both
                produce a name and artwork -- which is what the label above the
                pair says -- so "again" was the only thing distinguishing them,
                and "again" describes when it runs rather than what it uses.

                It matters because this one *does* replace a name you typed and
                the picker beside it does not. A button that says which input it
                trusts explains that; one that says "again" does not. */}
            <DialogButton onClick={() => void refetch()} style={BUTTON} disabled={busy}>
              {/* "by name" when the file has none of its own. A game installed
                  from a package boots eboot.bin, so "Look up by filename" would
                  be describing a search for "Eboot" -- the same search, and the
                  same nothing, for every PS3, PS4 and Vita game. */}
              {refreshing
                ? "Looking up..."
                : byFilename
                  ? "Look up by filename"
                  : "Look up by name"}
            </DialogButton>
          </div>
        </div>

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
      </Focusable>

      {note && (
        <div style={{ fontSize: "13px", opacity: 0.8, marginTop: "10px" }}>{note}</div>
      )}
      {error && (
        <div style={{ color: "#e35d5d", fontSize: "13px", marginTop: "10px" }}>{error}</div>
      )}

      <Focusable style={{ ...ROW, marginTop: "16px" }}>
        <DialogButton onClick={() => void save()} disabled={busy || !title.trim()}>
          {saving ? "Saving..." : "Save"}
        </DialogButton>
        <DialogButton onClick={() => void testLaunch()} disabled={busy || !title.trim()}>
          Save and test launch
        </DialogButton>
        <DialogButton onClick={() => closeModal?.()} disabled={busy}>
          Close
        </DialogButton>
      </Focusable>
    </ModalRoot>
  );
}
