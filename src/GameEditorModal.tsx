import {
  DialogButton,
  Dropdown,
  Focusable,
  ModalRoot,
  Spinner,
  TextField,
  showModal,
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
  launchApp,
  renameShortcut,
  repointShortcut,
} from "./steam";
import { unfileGames } from "./collections";
import { ArtPickerModal } from "./ArtPickerModal";
import { coreOptions as buildCoreOptions, isEmulatorId } from "./corePicker";
import { callWithRetry } from "./timeout";
import { logError } from "./logError";
import { sentence } from "./sentence";
import { titleAfterArtPick } from "./titleFromArt";

interface Props {
  game: AddedGame;
  onSaved: () => void;
  closeModal?: () => void;
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
export function GameEditorModal({ game, onSaved, closeModal }: Props) {
  const [title, setTitle] = useState(game.title);
  const [romPath, setRomPath] = useState(game.rom_path);
  const [coreId, setCoreId] = useState(game.core_id);
  const [cores, setCores] = useState<{ matching: Core[]; all: Core[] } | null>(null);
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
        setCores({ matching: probe.matching_cores, all: probe.all_cores });
        setShowAll(probe.matching_cores.length === 0);
      })
      .catch((probeError) => {
        if (!current) return;
        logError("could not probe ROM for editing", probeError);
        setError("Could not read that ROM, so the core list is unavailable.");
        setCores({ matching: [], all: [] });
      });
    return () => {
      current = false;
    };
  }, [romPath]);

  const visible = useMemo(() => {
    if (!cores) return [];
    return showAll || cores.matching.length === 0 ? cores.all : cores.matching;
  }, [cores, showAll]);

  // Shared with the add panel rather than built again here: this list had
  // already drifted once, staying flat after the panel learned to separate
  // emulators from cores.
  const coreOptions: DropdownOption[] = useMemo(() => buildCoreOptions(visible), [visible]);

  const isEmulator = isEmulatorId(coreId);

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
    showModal(
      <ArtPickerModal
        romPath={romPath}
        coreId={coreId}
        onApplied={(result) => {
          void (async () => {
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
            }

            toaster.toast({
              title: applied > 0 ? "Artwork updated" : "Artwork could not be applied",
              body: result.art_game_name || `${applied} image(s)`,
            });
          })();
        }}
      />,
    );
    // `title` is in here because the rule above reads it. Without it the
    // callback keeps the name the field had when the editor opened, so typing
    // a name and *then* picking a game threw the typed name away -- the one
    // case the rule exists to protect.
  }, [romPath, game.app_id, coreId, game.title, title]);

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
      const resolved = await resolveGame(romPath, coreId);
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
  }, [romPath, coreId, game.app_id, game.title]);

  const currentOptions = useCallback((): GameOptions => {
    const options: GameOptions = {};
    if (osd) options.hide_osd = osd as GameOptions["hide_osd"];
    if (fullscreen) options.fullscreen = fullscreen === "on";
    if (extraArgs.trim()) options.extra_args = extraArgs.trim();
    return options;
  }, [osd, fullscreen, extraArgs]);

  const save = useCallback(async () => {
    setSaving(true);
    setError("");
    try {
      const result = await updateGame(game.app_id, title, coreId, romPath, currentOptions());
      if (!result.ok) {
        setError(result.error);
        return;
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
      if (coreId !== game.core_id) notes.push(`now runs on ${result.platform}`);

      toaster.toast({
        title: result.title,
        // Each note reads correctly in the middle of a list and wrongly at the
        // front of one, and only the join knows which it ended up as.
        body: notes.length ? sentence(notes.join(", ")) : "Saved.",
      });
      onSaved();
      closeModal?.();
    } catch (saveError) {
      logError("could not save game", saveError);
      setError("Could not save those changes.");
    } finally {
      setSaving(false);
    }
  }, [game, title, coreId, romPath, currentOptions, onSaved, closeModal]);

  /**
   * Launch the game to check the change worked.
   *
   * Saves first: the launcher on disk is what Steam runs, so testing before
   * writing it would test the old settings. The panel closes because Steam is
   * about to take over the screen anyway.
   */
  const testLaunch = useCallback(async () => {
    await save();
    if (!launchApp(game.app_id)) {
      toaster.toast({
        title: "Could not start the game",
        body: "Steam did not accept the launch request. Try it from the library.",
      });
    }
  }, [save, game.app_id]);

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
              onChange={(option) => setCoreId(String(option.data))}
            />
          )}
          {cores && cores.matching.length > 0 && (
            <DialogButton onClick={() => setShowAll((previous) => !previous)} style={BUTTON}>
              {showAll ? "Show matching only" : "Show everything installed"}
            </DialogButton>
          )}
        </div>

        <div style={FIELD}>
          <Label
            hint={
              artApplied > 0
                ? `${artApplied} image(s) applied. Artwork lands immediately; a name change waits for Save.`
                : "Artwork lands immediately, a name change waits for Save. Looking up again uses the current core, which decides where boxart comes from."
            }
          >
            Name and artwork
          </Label>
          <div style={FIELD}>
            <DialogButton onClick={pickArtwork} style={BUTTON} disabled={busy}>
              Choose the right game
            </DialogButton>
            {/* "Name and artwork" stays in the label, and is not padding: this
                one *does* replace a name you typed, where the picker beside it
                leaves it alone. The difference is defensible only while the
                button says which it is -- the picker identifies a game and the
                name follows, this asks for the lookup to be run again, and the
                name is what it was asked for. "Re-fetch" was the only jargon
                left on the page. */}
            <DialogButton onClick={() => void refetch()} style={BUTTON} disabled={busy}>
              {refreshing ? "Looking up..." : "Look up name and artwork again"}
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
