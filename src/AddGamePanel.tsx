import {
  ButtonItem,
  DropdownItem,
  Field,
  Focusable,
  PanelSection,
  PanelSectionRow,
  showModal,
  Spinner,
  TextField,
  ToggleField,
  type DropdownOption,
  type SingleDropdownOption,
} from "@decky/ui";
import {
  addEventListener,
  removeEventListener,
  FileSelectionType,
  openFilePicker,
  toaster,
  useQuickAccessVisible,
} from "@decky/api";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  getSettings,
  installCore,
  installPs3Package,
  installPs4Package,
  installVitaPackage,
  listAdded,
  listInstalledPs3Games,
  listInstalledPs4Games,
  missingFirmware,
  listInstalledVitaGames,
  startFileServer,
  prepareShortcut,
  probeRom,
  type Core,
  type InstallableCore,
  type PluginSettings,
  type ResolvedGame,
  type RetroArchStatus,
} from "./backend";
import { addPreparedGame } from "./addGame";
import { getDraft, resetDraft, subscribeDraft, updateDraft } from "./romDraft";
import {
  LOOKUP_FAILED,
  lookupArtwork,
  selectPackagedGame,
  selectRom,
  type Console,
} from "./addFlow";
import { coreOptions as buildCoreOptions, installableOptions } from "./corePicker";
import { licenceChoice, pendingPackage as pendingPackageOf } from "./packageState";
import { PackagedGameEntries, PendingPackageRows } from "./PackageRows";
import { ArtPickerModal } from "./ArtPickerModal";
import { openManagePage } from "./manageRoute";
import { SGDB_PROMPT, sgdbKeyJustAppeared, shouldOfferSgdb } from "./sgdbPrompt";
import { TransferModal } from "./TransferModal";
import { logError } from "./logError";
import { sentence } from "./sentence";
import { titleAfterArtPick } from "./titleFromArt";


const MATCH_LABELS: Record<ResolvedGame["match_kind"], string> = {
  exact: "Matched libretro database",
  index: "Matched by name similarity",
  none: "No database match - name taken from filename",
};

interface Props {
  status: RetroArchStatus;
  onGameAdded: () => void;
}

export function AddGamePanel({ status, onGameAdded }: Props) {
  const [settings, setLocalSettings] = useState<PluginSettings | null>(null);
  // The draft lives outside React so it survives this panel being unmounted
  // while the file picker modal is open. See romDraft.ts.
  const [draft, setDraft] = useState(getDraft);
  // Unpacking a PS3 package. Local rather than in the draft: it is a transient
  // state of this panel, and nothing that survives a remount depends on it.
  const [unpacking, setUnpacking] = useState(false);
  const [unpackPercent, setUnpackPercent] = useState(0);
  const [unpackStatus, setUnpackStatus] = useState("");
  // Which licence key the user said belongs to a Vita package lives in the
  // draft, not here: choosing one opens a ContextMenu, which unmounts this
  // panel, so component state was discarded on the way back and the choice
  // reverted to the first candidate. See `installableId` for the same fault.

  // How many games RPCS3 has installed, so the route to them is offered only
  // when there is something behind it.
  const [ps3Count, setPs3Count] = useState(0);
  // Same for shadPS4, and for the same reason: its packages are deleted once
  // installed, so without this a game removed from the library is unreachable.
  const [ps4Count, setPs4Count] = useState(0);
  // Vita games have no other way in: the file was consumed by an installer we
  // did not run, so the list is the only place they exist to be picked from.
  const [vitaCount, setVitaCount] = useState(0);
  // What the chosen emulator still needs before anything it launches will run.
  // Read here rather than left to the Emulators tab: a shortcut made without a
  // BIOS boots to a black screen, and nothing on that screen mentions firmware.
  const [needs, setNeeds] = useState<{ emulator: string; names: string[] } | null>(null);

  useEffect(() => {
    const unsubscribe = subscribeDraft(setDraft);
    // Pick up anything that resolved while this panel was unmounted.
    setDraft(getDraft());
    return unsubscribe;
  }, []);

  // Re-read on every open, not once on mount. The SteamGridDB row below sends
  // people to the settings page to fix exactly what it is complaining about, and
  // it has to be gone when they come back -- otherwise the fix looks like it did
  // not take. The same applies to anything else changed over there.
  const visible = useQuickAccessVisible();

  useEffect(() => {
    getSettings().then(setLocalSettings).catch(() => undefined);
  }, [visible]);

  // Re-asked whenever the emulator changes, because the answer is about the
  // emulator and not the game. Cleared first so a stale warning from the last
  // core cannot sit under a newly chosen one.
  useEffect(() => {
    setNeeds(null);
    if (!draft.coreId) return;
    let current = true;
    missingFirmware(draft.coreId)
      .then((result) => {
        const names = (result.missing ?? []).map((item) => item.name);
        if (current && names.length) {
          setNeeds({ emulator: result.emulator ?? "This emulator", names });
        }
      })
      .catch(() => undefined);
    return () => {
      current = false;
    };
  }, [draft.coreId]);

  // Whether RPCS3, shadPS4 or Vita3K has anything installed, which decides
  // whether the route to them is worth a row. Counted rather than listed: the
  // lists are read when the modals open, and these only answer yes or no.
  useEffect(() => {
    // Counted after subtracting what is already in the library, so the number
    // on the button matches the number of rows behind it. Advertising "(2)"
    // and then opening an empty list is worse than not offering the button.
    Promise.all([
      listInstalledPs3Games(),
      listInstalledPs4Games(),
      listInstalledVitaGames(),
      listAdded(),
    ])
      .then(([ps3, ps4, vita, added]) => {
        const inSteam = new Set(added.map((game) => game.rom_path));
        const addable = (list: { eboot: string }[]) =>
          list.filter((game) => !inSteam.has(game.eboot)).length;
        setPs3Count(addable(ps3.games ?? []));
        setPs4Count(addable(ps4.games ?? []));
        setVitaCount(addable(vita.games ?? []));
      })
      .catch(() => undefined);
  }, [draft.romPath]);

  const {
    romPath,
    titleId,
    probe,
    coreId,
    showAllCores,
    resolved,
    title,
    installable,
    installableId,
    keyChoice,
    looking,
    adding,
    installingCore,
    error,
  } = draft;

  const lookup = lookupArtwork;

  /**
   * Look again for a Vita package's licence key whenever this panel comes back.
   *
   * The advice for a missing key is "send it to the same folder", and doing
   * that means opening the transfer modal — which unmounts this panel, because
   * Steam unmounts Quick Access content behind a modal. So the user follows the
   * instruction, comes back, and the row still says the key is missing: the
   * probe ran once, when the ROM was picked, and nothing has re-read the folder
   * since. The only way out was to pick the same file again, which nothing
   * suggests.
   *
   * Remounting is exactly the moment to re-check, and it is free: this runs
   * only while a package is sitting here waiting for a key it does not have.
   * There is no event to use instead — a file arriving over the transfer server
   * emits nothing, which is why the transfer row polls.
   */
  useEffect(() => {
    if (!romPath || probe?.vita_package?.licence !== false) return;
    let live = true;
    void probeRom(romPath)
      .then((info) => {
        // Only when it changes, or this writes the draft on every mount and
        // re-renders the panel for nothing.
        if (live && info.vita_package?.licence !== probe.vita_package?.licence) {
          updateDraft({ probe: info });
        }
      })
      .catch((probeError) => {
        // A failed re-check leaves what is on screen, which is the truth as of
        // the last read. Nothing here is worth an error row.
        logError("could not re-check the licence key", probeError);
      });
    return () => {
      live = false;
    };
    // Deliberately keyed on the ROM and the answer, not on `probe`: the effect
    // writes `probe`, so depending on the whole object would re-run it on its
    // own result.
  }, [romPath, probe?.vita_package?.licence]);

  /**
   * RPCS3's own output while it unpacks, which only fills the bar.
   *
   * Deliberately not how the unpack finishes: `installPs3Package` resolves when
   * it is done. An earlier version ended the step on a `ps3_install_done` event
   * and the panel sat on "Unpacking" over an install that had completed five
   * seconds earlier, because the one message that mattered went by a channel
   * nothing else depended on. Losing these costs a progress bar.
   */
  useEffect(() => {
    const onProgress = (_name: string, text: string, percent: number) => {
      setUnpackStatus(text.length > 110 ? `${text.slice(0, 107)}...` : text);
      if (percent >= 0) setUnpackPercent(Math.max(0, Math.min(100, percent)));
    };
    // Both consoles, because only one of them can be unpacking at a time and
    // the bar does not care which.
    const listeners = ([
      "ps3_install_progress", "ps4_install_progress", "vita_install_progress",
    ] as const).map(
      (event) => [event, addEventListener<[string, string, number]>(event, onProgress)] as const,
    );
    return () => {
      for (const [event, listener] of listeners) removeEventListener(event, listener);
    };
  }, []);

  /**
   * Unpacking a PlayStation 3 package, which is a step no other system has.
   *
   * A .pkg is not a game until RPCS3 has unpacked it, so the add flow stops
   * here and carries on afterwards from the EBOOT.BIN that came out -- see
   * `selectPs3Game`. No window opens: `--headless --installpkg` does a 240MB
   * package in about five seconds with nothing on screen.
   */
  const unpackPackage = useCallback((system: Console, keyName = "") => {
    if (!romPath) return;
    updateDraft({ error: "" });
    setUnpacking(true);
    setUnpackPercent(0);
    setUnpackStatus("Starting...");
    void (async () => {
      try {
        const result =
          system === "ps4"
            ? await installPs4Package(romPath)
            : system === "vita"
              ? // `keyName` is only set when the user picked a key that is not
                // named for this game. Without it the backend uses the one
                // named after the package, and refuses rather than guessing.
                await installVitaPackage(romPath, keyName)
              : await installPs3Package(romPath);
        if (!result.ok || !result.title_id) {
          updateDraft({ error: result.error ?? "The package did not install." });
          return;
        }
        toaster.toast({
          title: `${result.title} installed`,
          // Worth saying: a licence going in without being asked for is the
          // difference between a game that boots and one that does not.
          body:
            "licence" in result && result.licence
              ? "Its licence was installed too. Finding its artwork."
              : "Finding its artwork.",
        });
        await selectPackagedGame(system, result.title_id);
      } catch (installError) {
        logError("PS3 package install failed", installError);
        updateDraft({
          error:
            installError instanceof Error
              ? installError.message
              : "The package did not install.",
        });
      } finally {
        // In a finally, so no path out of here can leave the panel claiming to
        // still be unpacking -- which is the whole reason this was rewritten.
        setUnpacking(false);
        setUnpackPercent(0);
        setUnpackStatus("");
      }
    })();
  }, [romPath]);

  const pickRom = useCallback(async () => {
    updateDraft({ error: "" });

    // openFilePicker *rejects* when the user backs out, so a cancel has to be
    // told apart from a real failure -- otherwise dismissing the browser looks
    // like an error.
    let picked: { path: string; realpath: string } | undefined;
    try {
      // A transferred file still waiting to be added, else where a ROM was last
      // picked from, else the backend's default (home). No hardcoded path: the
      // backend resolves the real home, which is not /home/deck on every install.
      //
      // The inbox wins because the received list is the only other way back to a
      // sent file and it does not survive a reload -- after one, the file is on
      // disk with nothing pointing at it. It is only ever set when something is
      // actually in there, so it cannot open an empty folder.
      const startPath =
        status.waiting_rom_dir || settings?.last_rom_dir || status.default_rom_dir;
      picked = await openFilePicker(
        FileSelectionType.FILE,
        startPath,
        true,
        true,
        undefined,
        undefined,
        false,
        true,
      );
    } catch (pickError) {
      const message = String(pickError ?? "");
      if (message.toLowerCase().includes("cancel")) {
        console.log("[deckyemu] ROM selection cancelled");
      } else {
        logError("file picker failed", pickError);
        updateDraft({ error: "Could not open the file browser." });
      }
      return;
    }

    // The picker's footer button submits the current *directory*, so a path
    // without a filename is a real possibility rather than an edge case.
    const path = picked?.realpath || picked?.path || "";
    console.log("[deckyemu] picked", picked);
    if (!path) {
      updateDraft({ error: "That selection did not return a file path." });
      return;
    }

    await selectRom(path);
  }, [settings?.last_rom_dir, status.default_rom_dir, status.waiting_rom_dir]);

  const visibleCores: Core[] = useMemo(() => {
    if (!probe) return [];
    return showAllCores || probe.matching_cores.length === 0
      ? probe.all_cores
      : probe.matching_cores;
  }, [probe, showAllCores]);

  const coreOptions: DropdownOption[] = useMemo(
    () => buildCoreOptions(visibleCores),
    [visibleCores],
  );

  /**
   * Which suggested core the install button would install; "" means the first.
   *
   * Read from the draft, not from component state: opening this dropdown opens a
   * ContextMenu, which unmounts the panel behind it the way a modal does, so a
   * `useState` selection is gone by the time the menu closes and the list snaps
   * back to its first entry. Resolved by lookup rather than by index so a stale
   * id from a previous ROM falls back instead of picking the wrong core.
   */
  const chosenInstallable = useMemo(
    () => installable.find((core) => core.id === installableId) || installable[0],
    [installable, installableId],
  );

  /*
   * Look the artwork up again when a key appears mid-flow.
   *
   * The prompt sends people to the settings page while a ROM is still in the
   * draft, and what was found for it was found without a key. Without this,
   * following that advice and coming straight back adds the game with the same
   * single image it was already showing -- which reads as the key not working.
   *
   * The memory of the previous state is in `sgdbPrompt`, at module scope,
   * because this component does not survive the trip to the settings page.
   *
   * Ordered so nothing is consumed that cannot be acted on: while a lookup is
   * already running this returns before asking, and runs again when `looking`
   * goes false. With no ROM the transition is consumed and dropped, which is
   * right -- the next ROM picked is looked up with the key anyway.
   */
  useEffect(() => {
    if (!settings || looking) return;
    if (!sgdbKeyJustAppeared(settings)) return;
    if (!romPath || !coreId) return;
    // Read at call time rather than through a dependency, so editing the name
    // does not re-run this on every keystroke.
    void lookupArtwork(romPath, coreId, getDraft().title);
  }, [settings, romPath, coreId, looking]);

  const onCoreChange = useCallback(
    (option: SingleDropdownOption) => {
      const nextCore = String(option.data);
      updateDraft({ coreId: nextCore });
      void lookup(romPath, nextCore);
    },
    [romPath, lookup],
  );

  /** Install a core for a ROM nothing can currently run, then re-probe. */
  const installAndUse = useCallback(
    async (core: InstallableCore) => {
      updateDraft({ installingCore: core.id, error: "" });
      try {
        const result = await installCore(core.id);
        if (!result.ok) {
          updateDraft({ error: result.error, installingCore: "" });
          return;
        }
        const info = await probeRom(romPath);
        const nextCore = info.suggested_core_id || core.id;
        updateDraft({
          probe: info,
          installable: [],
          installableId: "",
          coreId: nextCore,
          installingCore: "",
        });
        await lookup(romPath, nextCore);
        toaster.toast({
          title: `Installed ${core.display_name}`,
          body: "Ready to add this game.",
        });
      } catch (installError) {
        logError("core install failed", installError);
        updateDraft({ error: "Could not install that core.", installingCore: "" });
      }
    },
    [romPath, lookup],
  );

  /** Correct a wrong artwork match by hand. */
  const openArtPicker = useCallback(() => {
    if (!romPath) return;
    showModal(
      <ArtPickerModal
        romPath={romPath}
        coreId={coreId}
        onApplied={(result) => {
          const draft = getDraft();
          const current = draft.resolved;

          // The name comes with the artwork, unless the user wrote their own.
          // See titleFromArt.ts, which the editor uses for the same decision.
          const nextTitle = titleAfterArtPick(
            draft.title,
            current?.title ?? "",
            result.suggested_title,
          );

          updateDraft({
            title: nextTitle,
            resolved: {
              // The lookup's own title, not the one above: `matched_name` and
              // `match_kind` describe how the *name* was found, and rewriting
              // them here would claim the database matched something it did not.
              title: current?.title ?? nextTitle,
              system: current?.system ?? "",
              matched_name: current?.matched_name ?? "",
              match_kind: current?.match_kind ?? "none",
              core_id: coreId,
              rom_path: romPath,
              art: result.art,
              art_source: result.art_source,
              art_game_name: result.art_game_name,
            },
          });

          toaster.toast({
            title:
              nextTitle === draft.title ? "Artwork updated" : "Artwork and name updated",
            body: result.art_game_name || "New artwork applied.",
          });
        }}
      />,
    );
  }, [romPath, coreId, title]);

  const addToSteam = useCallback(async () => {
    if (!romPath || !coreId) return;
    updateDraft({ adding: true, error: "" });

    try {
      // The resolved system decides the collection for a core covering more
      // than one; without it Dolphin filed Wii games under GameCube.
      const prepared = await prepareShortcut(
        title, coreId, romPath, resolved?.system ?? "", titleId,
      );
      if (!prepared.ok) {
        updateDraft({ error: prepared.error, adding: false });
        return;
      }

      // Shortcut, artwork, collection, registry -- in that order, and rolled
      // back on failure. See addGame.ts; the Vita list runs the same steps.
      const added = await addPreparedGame({
        prepared,
        romPath,
        coreId,
        system: resolved?.system ?? "",
        art: resolved?.art,
      });

      const notes: string[] = [];
      notes.push(
        added.artApplied > 0
          ? `${added.artApplied} artwork image(s) applied`
          : "no artwork found",
      );
      if (prepared.collection_name && !added.collection) {
        // Said rather than swallowed: the game is in the library and playable,
        // but it is not on the shelf the panel implied it would be on, and the
        // library check is where that gets repaired.
        notes.push("could not add it to its collection");
      }
      if (prepared.warn_flatpak_sdcard) {
        notes.push("SD card access granted to the RetroArch flatpak");
      }

      toaster.toast({
        title: `Added ${prepared.title}`,
        body: sentence(notes.join(" - ")),
      });

      onGameAdded();
      resetDraft();
    } catch (addError) {
      logError("add failed", addError);
      updateDraft({
        adding: false,
        error:
          addError instanceof Error ? addError.message : "Failed to add the game to Steam.",
      });
    }
  }, [romPath, titleId, coreId, title, resolved, onGameAdded]);

  /**
   * Start receiving, then show the QR code in a modal.
   *
   * Started before the modal opens rather than inside it: nothing then depends on
   * when a component mounts, which is what made the previous attempt at this
   * silently do nothing. An empty folder argument means the backend picks the
   * default, so this is a single call.
   */
  const openTransfer = useCallback(async () => {
    try {
      const result = await startFileServer("");
      if (!result.ok) {
        toaster.toast({
          title: "Could not start receiving",
          body: result.error ?? "You can try again from the dialog.",
        });
      }
    } catch (transferError) {
      logError("could not start the file server", transferError);
    }
    showModal(<TransferModal />);
  }, []);

  // A custom emulator is enough on its own, so do not require RetroArch here.
  if (!status.found && status.emulator_count === 0) {
    return null;
  }

  const romName = romPath ? romPath.slice(romPath.lastIndexOf("/") + 1) : "";
  const capsule = resolved?.art?.capsule?.data;
  const canAdd = Boolean(romPath && coreId && title.trim() && !adding && !looking);

  // What this file is, if it is a package rather than a ROM, and which licence
  // it would go in under. Derived rather than held: see packageState.ts, which
  // is where these live so vitest can reach the licence decision -- there is no
  // DOM here, so anything only reachable by rendering the panel is untested.
  const pendingPackage = pendingPackageOf(probe);
  const licence = licenceChoice(pendingPackage, keyChoice);

  return (
    <PanelSection title="Add a game">
      {/* Getting the file here comes before picking it, so it is the first row.
          It was the second, under a picker offering to browse for a game that
          was still on somebody's PC.

          Hidden once a ROM is chosen: at that point the file is here and the
          rest of the panel is about what to do with it. */}
      {!romPath && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => void openTransfer()}
            disabled={adding}
            description="Send games over the local network from a phone or PC. They arrive in the transfer folder, ready to choose below."
          >
            Transfer to Deck
          </ButtonItem>
        </PanelSectionRow>
      )}

      <PanelSectionRow>
        <ButtonItem layout="below" onClick={pickRom} disabled={adding}>
          {/* Wrapped rather than left to overflow. A .pkg arrives named
              UP4415-NPUB31749_00-GOATSIMULATORPS3_bg_1_fbd920a6…pkg -- a
              hundred characters with not one space in them, so there is no
              break for the layout to find and the text runs straight out of
              the button. `anywhere` lets it break mid-word; the button grows
              a line or two instead. Kept whole rather than truncated: the
              interesting part of these names is the end. */}
          <div style={{ overflowWrap: "anywhere", whiteSpace: "normal" }}>
            {/* "Choose a game" rather than "Add to Library": this opens a file
                browser, and the button that actually adds one is at the bottom
                of the same panel saying "Add to Steam". Two buttons claiming to
                add would be worse than a plain description of what each does. */}
            {romName || "Choose a game"}
          </div>
        </ButtonItem>
      </PanelSectionRow>

      {/* Only while no ROM is chosen: these are a way in, and once a file is
          here the rest of the panel is about that file. */}
      {!romPath && (
        <PackagedGameEntries
          ps3Count={ps3Count}
          ps4Count={ps4Count}
          vitaCount={vitaCount}
          disabled={adding}
          onGameAdded={onGameAdded}
        />
      )}

      {probe?.unsupported_extension && (
        <PanelSectionRow>
          <Field
            label="Unusual file type"
            description={`.${probe.extension} is normally a save or config file, not a ROM.`}
          />
        </PanelSectionRow>
      )}

      {/* A warning rather than a refusal: the file is odd, not forbidden, and
          somebody who knows better should still be able to add it. */}
      {probe?.disc_warning && (
        <PanelSectionRow>
          <Field label="Nothing to boot on this disc" description={probe.disc_warning} />
        </PanelSectionRow>
      )}

      {/* The emulator itself is not ready, whatever the game is.
          This is the same kind of warning as the two below it and by far the
          most common failure they were missing: a PS2, PS1, Wii U, 3DS or
          Switch game added with no BIOS or keys gets a shortcut, silence and a
          black screen, and nothing on that screen mentions firmware. Said, not
          enforced — a missing BIOS is usually fatal and occasionally not, and
          refusing would be a guess. */}
      {needs && (
        <PanelSectionRow>
          <Field
            label={`${needs.emulator} is missing ${needs.names.length === 1 ? "something" : "some things"}`}
            description={`${needs.names.join(", ")} — the game will be added, but is unlikely to start until this is supplied. Emulators tab, under BIOS and firmware.`}
          />
        </PanelSectionRow>
      )}

      {/* Everything about a game that arrived as a package: what its licence
          situation is, and the button that installs it. See PackageRows.tsx --
          two hundred lines of this panel's return, and one subject. */}
      <PendingPackageRows
        packaged={pendingPackage}
        probe={probe}
        licence={licence}
        unpacking={unpacking}
        unpackPercent={unpackPercent}
        unpackStatus={unpackStatus}
        adding={adding}
        onInstall={(keyName) => pendingPackage && unpackPackage(pendingPackage.system, keyName)}
      />

      {probe && !pendingPackage && probe.matching_cores.length > 0 && (
        <>
          <PanelSectionRow>
            <DropdownItem
              // Below, not beside. An inline Item puts its value in the
              // right-hand half of the row and truncates it there, and the
              // Quick Access panel has too little width to spend half of it on
              // a label. Core names do not survive it: every libretro name for
              // one system shares its opening words, so the half that gets
              // shown is the half every option has in common.
              layout="below"
              // Not "Core": half the list is standalone emulators, which are
              // not cores and do not run inside RetroArch.
              label="Run with"
              description={
                `${probe.matching_cores.length} of these support .${probe.match_extension}` +
                (probe.is_archive && probe.match_extension !== probe.extension
                  ? ` (found inside the .${probe.extension})`
                  : "")
              }
              rgOptions={coreOptions}
              selectedOption={coreId}
              onChange={onCoreChange}
              disabled={adding || coreOptions.length === 0}
            />
          </PanelSectionRow>

          <PanelSectionRow>
            <ToggleField
              label="Show everything installed"
              description="Include cores and emulators that do not list this file extension"
              checked={showAllCores}
              onChange={(value) => updateDraft({ showAllCores: value })}
              disabled={adding}
            />
          </PanelSectionRow>
        </>
      )}

      {/* Nothing claims this file. Forcing something installed is sometimes
          right and this is the only way to do it -- but only when there is
          nothing better to offer.

          Suppressed while there are cores to install, because those are the
          answer to this file and this row is not: with five emulators
          registered and no cores, it offered Cemu, Dolphin, DuckStation, PCSX2
          and Ryujinx as ways to run a Game Boy Color ROM, above the twenty
          cores that actually could. Not an empty control -- a full one, whose
          every entry is wrong. Two "what should run this" rows where the first
          cannot answer is worse than one.

          `coreOptions.length` as well, since with nothing registered and no
          cores the list is empty and a disabled dropdown says even less. */}
      {probe && !pendingPackage && probe.matching_cores.length === 0
        && installable.length === 0 && coreOptions.length > 0 && (
        <PanelSectionRow>
          <DropdownItem
            layout="below"
            label="Run with"
            description={`Nothing installed claims .${probe.match_extension}`}
            rgOptions={coreOptions}
            selectedOption={coreId}
            onChange={onCoreChange}
            disabled={adding}
          />
        </PanelSectionRow>
      )}

      {/* Cores exist for this file, but there is no RetroArch to put one in.
          Offering the picker anyway gives a button whose only possible outcome
          is "RetroArch was not found on this system." in red at the bottom of
          the panel, which on a Deck is below the fold -- so pressing it reads
          as nothing happening at all. Say what is missing, and go there. */}
      {installable.length > 0 && !status.found && (
        <>
          <PanelSectionRow>
            <Field
              label="RetroArch is not installed"
              description={
                `${installable.length} core${installable.length === 1 ? "" : "s"}` +
                ` can run .${probe?.match_extension}, and a core needs RetroArch to run in.`
              }
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => openManagePage("retroarch")}>
              Install RetroArch
            </ButtonItem>
          </PanelSectionRow>
        </>
      )}

      {installable.length > 0 && status.found && chosenInstallable && (
        <>
          {/* Only when there is a choice to make. A dropdown holding one option
              is a control that does nothing -- it reads as a choice and offers
              none, and for several systems one is the true answer: exactly one
              libretro core claims .wux, and none claims .pkg. The button below
              already names what it would install, so a single suggestion is
              fully described without a row above it. */}
          {installable.length > 1 ? (
            <PanelSectionRow>
              <DropdownItem
                // Below rather than beside: an inline Item gives the value the
                // right-hand half of the row and truncates it there, which is
                // where a core name goes to be unreadable. Full width costs one
                // line and shows the whole name.
                layout="below"
                label="No core installed for this ROM"
                description={`These can run .${probe?.match_extension} — install one to continue.`}
                rgOptions={installableOptions(installable)}
                selectedOption={chosenInstallable.id}
                onChange={(option) => updateDraft({ installableId: String(option.data) })}
                disabled={Boolean(installingCore) || adding}
              />
            </PanelSectionRow>
          ) : (
            <PanelSectionRow>
              <Field
                label="No core installed for this ROM"
                // Names it here because there is no dropdown above the button
                // saying which one, and the button is only the verb. Full name
                // rather than the short one: a description is full width, and
                // this is the one place the system is not already established.
                description={`${chosenInstallable.display_name} can run .${probe?.match_extension}.`}
              />
            </PanelSectionRow>
          )}
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              onClick={() => void installAndUse(chosenInstallable)}
              disabled={Boolean(installingCore) || adding}
            >
              {/* Not the core's name again: the dropdown above already says
                  which one, and repeating a forty-character libretro name here
                  made the button wrap to two lines to restate it. Matches the
                  Cores tab, where the button under the picker is just the verb. */}
              {installingCore ? "Installing..." : "Install this core"}
            </ButtonItem>
          </PanelSectionRow>
        </>
      )}

      {looking && (
        <PanelSectionRow>
          <Field label="Looking up name and artwork">
            <Spinner style={{ height: "20px" }} />
          </Field>
        </PanelSectionRow>
      )}

      {/* Not while a package is waiting to be unpacked: the only name available
          then is the .pkg's filename, and the real one comes from the game's
          own PARAM.SFO a few seconds later. Offering it for editing first
          invites a name that is then overwritten. */}
      {romPath && !looking && !pendingPackage && (
        <PanelSectionRow>
          <TextField
            label="Name in Steam"
            value={title}
            bShowClearAction
            // Room for the clear button, which Steam draws over the input
            // rather than beside it -- so a title long enough to reach the
            // right-hand edge ran underneath the X. Reserved here because the
            // component gives no way to ask for it, and TextFieldProps extends
            // the input's own attributes, so a style lands where it is needed.
            style={{ paddingRight: "2.6em" }}
            onChange={(event) => updateDraft({ title: event.target.value })}
            disabled={adding}
          />
        </PanelSectionRow>
      )}

      {resolved && !looking && (
        <PanelSectionRow>
          <Field
            label="Artwork"
            description={
              resolved.art_source === "none"
                ? MATCH_LABELS[resolved.match_kind]
                : resolved.art_source === "steamgriddb"
                  ? // Name the SteamGridDB game: its search can return a
                    // different title, and seeing it beats guessing.
                    `SteamGridDB${
                      resolved.art_game_name ? ` - "${resolved.art_game_name}"` : ""
                    }`
                  : `libretro thumbnails - ${MATCH_LABELS[resolved.match_kind]}`
            }
          >
            {capsule ? (
              <img
                src={capsule}
                alt=""
                style={{
                  height: "108px",
                  width: "72px",
                  objectFit: "cover",
                  borderRadius: "4px",
                }}
              />
            ) : (
              <span style={{ opacity: 0.6 }}>None</span>
            )}
          </Field>
        </PanelSectionRow>
      )}

      {/* Under the artwork row, because that is what it is about, and only once
          artwork has been looked up -- before then there is nothing on screen for
          it to be a remark on. It disappears by itself the moment a key exists;
          there is no dismissal, because the row asks for one thing and having
          done it is the only signal needed. See sgdbPrompt.ts. */}
      {resolved && !looking && shouldOfferSgdb(settings) && (
        <>
          <PanelSectionRow>
            <Field label={SGDB_PROMPT.label} description={SGDB_PROMPT.description} />
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => openManagePage("artwork")}>
              {SGDB_PROMPT.action}
            </ButtonItem>
          </PanelSectionRow>
        </>
      )}

      {error && (
        <PanelSectionRow>
          <Focusable>
            <div style={{ color: "#e35d5d", fontSize: "13px", padding: "4px 0" }}>{error}</div>
          </Focusable>
        </PanelSectionRow>
      )}

      {/* Adding is the primary action, so it leads. Correcting the artwork is a
          follow-up, and clearing is the least likely of the three.

          Hidden entirely until a ROM is picked. A permanently disabled button is
          the panel's largest control saying nothing -- while a ROM *is* picked it
          stays visible but disabled, because then it is telling you something is
          still missing, usually a core. */}
      {romPath && (
        <PanelSectionRow>
          {/* Not blocked outright. The check is good enough to warn on and not
              good enough to overrule somebody with the file in front of them:
              a disc image this cannot parse is reported as fine, so the errors
              it can make are not all in the safe direction. What it does buy is
              that nobody adds one of these by accident — the button says what
              it is about to do. */}
          <ButtonItem
            layout="below"
            onClick={addToSteam}
            disabled={!canAdd}
            description={
              probe?.disc_warning && !adding
                ? "This will be added and will not boot."
                : undefined
            }
          >
            {adding
              ? "Adding..."
              : probe?.disc_warning
                ? "Add anyway"
                : "Add to Steam"}
          </ButtonItem>
        </PanelSectionRow>
      )}

      {romPath && !looking && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={openArtPicker} disabled={adding}>
            {/* The words on the screen this opens, which has always called
                itself "Choose the right game" -- and is right, now that picking
                an entry sets the name as well as the cover. Two states because
                the situations differ: a wrong cover is visible and worth
                questioning, no cover at all is just missing. */}
            {resolved?.art?.capsule
              ? "Wrong game? Choose the right one"
              : "Choose the right game"}
          </ButtonItem>
        </PanelSectionRow>
      )}

      {/* Only after the lookup itself failed, which is the one state nothing
          else here answers. Changing the core re-runs it, a key arriving
          re-runs it, and a name that came out wrong is better fixed in the art
          picker's search box, where the candidates are visible. What none of
          those cover is a lookup that never finished: the reply was lost, so
          there is nothing to correct and nothing to choose between -- just the
          same request, worth making again. */}
      {romPath && !looking && error === LOOKUP_FAILED && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => void lookupArtwork(romPath, coreId, title)}
            disabled={adding || !coreId}
          >
            Try the lookup again
          </ButtonItem>
        </PanelSectionRow>
      )}

      {romPath && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => resetDraft()} disabled={adding}>
            Clear
          </ButtonItem>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}
