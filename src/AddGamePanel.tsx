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
  registerGame,
  type Core,
  type InstallableCore,
  type PluginSettings,
  type ResolvedGame,
  type RetroArchStatus,
} from "./backend";
import { addToCollection, applyArtwork, removeShortcut } from "./steam";
import { createOrReuseShortcut } from "./reuseShortcut";
import { getDraft, resetDraft, subscribeDraft, updateDraft } from "./romDraft";
import {
  LOOKUP_FAILED,
  lookupArtwork,
  selectPackagedGame,
  selectRom,
  type Console,
} from "./addFlow";
import { coreOptions as buildCoreOptions } from "./corePicker";
import { ArtPickerModal } from "./ArtPickerModal";
import { openManagePage } from "./ManagePage";
import { SGDB_PROMPT, sgdbKeyJustAppeared, shouldOfferSgdb } from "./sgdbPrompt";
import { InstallProgress } from "./InstallProgress";
import { PackagedGamesModal } from "./PackagedGamesModal";
import { TransferModal } from "./TransferModal";
import { VitaGamesModal } from "./VitaGamesModal";


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
    looking,
    adding,
    installingCore,
    error,
  } = draft;

  const lookup = lookupArtwork;

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
  const unpackPackage = useCallback((system: Console) => {
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
              ? await installVitaPackage(romPath)
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
        console.error("[deckyemu] PS3 package install failed", installError);
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
      // Where a ROM was last picked from, else the backend's default (home).
      // No hardcoded path: the backend resolves the real home, which is not
      // /home/deck on every install.
      const startPath = settings?.last_rom_dir || status.default_rom_dir;
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
        console.error("[deckyemu] file picker failed", pickError);
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
  }, [settings?.last_rom_dir, status.default_rom_dir]);

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
          coreId: nextCore,
          installingCore: "",
        });
        await lookup(romPath, nextCore);
        toaster.toast({
          title: `Installed ${core.display_name}`,
          body: "Ready to add this game.",
        });
      } catch (installError) {
        console.error("[deckyemu] core install failed", installError);
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
          const current = getDraft().resolved;
          updateDraft({
            resolved: {
              // Keep the rest of the resolution; only the artwork changed.
              title: current?.title ?? title,
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
            title: "Artwork updated",
            body: result.art_game_name || "New artwork applied.",
          });
        }}
      />,
    );
  }, [romPath, coreId, title]);

  const addToSteam = useCallback(async () => {
    if (!romPath || !coreId) return;
    updateDraft({ adding: true, error: "" });

    let createdAppId = 0;
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

      // Takes over an existing shortcut for this launcher rather than adding a
      // second one beside it. See reuseShortcut.ts -- the case that produced
      // duplicates is a lost registry, where the plugin has forgotten a game
      // Steam still has.
      const shortcut = await createOrReuseShortcut({
        title: prepared.title,
        exe: prepared.exe,
        startDir: prepared.start_dir,
        launchOptions: prepared.launch_options,
      });
      createdAppId = shortcut.appId;

      const artApplied = resolved?.art ? await applyArtwork(createdAppId, resolved.art) : 0;

      // The backend resolves this, so per-platform naming lives in one place.
      if (prepared.collection_name) {
        await addToCollection(createdAppId, prepared.collection_name);
      }

      await registerGame(
        createdAppId,
        prepared.title,
        // Where the ROM ended up, not where it was picked from: adding a game
        // files it out of the transfer folder and into one named after its
        // system, and the library has to record the path the launcher runs or
        // every filed game reads as an orphan.
        prepared.rom_path || romPath,
        coreId,
        prepared.launcher_path,
        resolved?.system ?? "",
      );

      const notes: string[] = [];
      notes.push(artApplied > 0 ? `${artApplied} artwork image(s) applied` : "no artwork found");
      if (prepared.warn_flatpak_sdcard) {
        notes.push("SD card access granted to the RetroArch flatpak");
      }

      toaster.toast({
        title: `Added ${prepared.title}`,
        body: notes.join(" - "),
      });

      onGameAdded();
      resetDraft();
    } catch (addError) {
      console.error("[deckyemu] add failed", addError);
      // Do not leave a half-built shortcut behind.
      if (createdAppId) removeShortcut(createdAppId);
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
      console.error("[deckyemu] could not start the file server", transferError);
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

  // A package still to be unpacked, from either console. Once it has been, the
  // draft points at the game inside it and this is gone, so the panel only ever
  // shows one of the two states.
  const packaged = probe?.ps4_package
    ? ({ system: "ps4", state: probe.ps4_package } as const)
    : probe?.vita_package
      ? ({ system: "vita", state: probe.vita_package } as const)
      : probe?.ps3_package
        ? ({ system: "ps3", state: probe.ps3_package } as const)
        : null;
  const pendingPackage = packaged && !packaged.state.installed ? packaged : null;

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

      {/* A PS3 or PS4 game is the one thing with no ROM to point the picker at:
          the .pkg was consumed installing it, and what boots lives inside a
          hidden directory under a product code. Without this row, a game
          removed from the library and kept on disk could only be added back by
          typing that path. */}
      {!romPath && ps3Count > 0 && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => showModal(<PackagedGamesModal system="ps3" />)}
            disabled={adding}
            description="Games RPCS3 has already installed. They have no ROM file to browse to, so this is the way back to them."
          >
            {`PlayStation 3 games in RPCS3 (${ps3Count})`}
          </ButtonItem>
        </PanelSectionRow>
      )}

      {!romPath && ps4Count > 0 && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => showModal(<PackagedGamesModal system="ps4" />)}
            disabled={adding}
            description="Games shadPS4 has already installed. They have no ROM file to browse to, so this is the way back to them."
          >
            {`PlayStation 4 games in shadPS4 (${ps4Count})`}
          </ButtonItem>
        </PanelSectionRow>
      )}

      {/* Vita3K installs and decrypts its own games, so unlike every other
          system here there is no file to pick — the installed list is the only
          door in. */}
      {!romPath && vitaCount > 0 && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => showModal(<VitaGamesModal onAdded={onGameAdded} />)}
            disabled={adding}
            description="Games Vita3K has installed. It decrypts them as it installs, so they are added from here rather than by choosing a file."
          >
            {`PlayStation Vita games in Vita3K (${vitaCount})`}
          </ButtonItem>
        </PanelSectionRow>
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

      {/* A PS3 store game needs its .rap, and RPCS3 reads one only under the
          package's own content id. Said here, before the install, because the
          alternative is finding out from "Failed to decrypt content" on a
          black screen — and because naming the file is the whole fix. */}
      {/* Shown while the package is still a package, which is the only moment
          this can be known: the content id comes out of the .pkg header, and
          the .pkg is deleted once it installs. It is also the moment the
          warning is most use, since the licence can be sent before unpacking
          rather than discovered afterwards. */}
      {pendingPackage?.system === "ps3" &&
        pendingPackage.state.licence_state === "" &&
        pendingPackage.state.content_id && (
          <PanelSectionRow>
            <Field
              label="No licence for this game"
              description={
                `Store games need a .rap licence. Send it to the same folder as ` +
                `the game and it goes in when the game does — it is renamed for ` +
                `you. If there is more than one .rap there, name this one ` +
                `${pendingPackage.state.content_id}.rap so it can be told apart. ` +
                `Licence-free games work without one.`
              }
            />
          </PanelSectionRow>
        )}

      {/* Said even though there is nothing to do, because the alternative is
          what happened: a licence already in place looks exactly like a check
          that never ran, and the only way to tell them apart was to go and
          look in exdata over ssh. All three answers are now visible. */}
      {pendingPackage?.system === "ps3" &&
        pendingPackage.state.licence_state === "installed" && (
          <PanelSectionRow>
            <Field
              label="Licence installed"
              description="RPCS3 already has this game's .rap, from an earlier install. Nothing to send."
            />
          </PanelSectionRow>
        )}

      {/* Nothing to do — the install puts it in place. Said anyway, because
          "your licence is here and will be used" is worth knowing before
          pressing a button on a game that would otherwise not boot. */}
      {pendingPackage?.system === "ps3" &&
        pendingPackage.state.licence_state === "waiting" && (
          <PanelSectionRow>
            <Field
              label="Licence found"
              description="This game's .rap is here and will be installed along with it."
            />
          </PanelSectionRow>
        )}

      {/* Vita3K installs a release the first time it is launched, so there is
          no unpack step here — but a missing licence is worth saying before
          the game refuses to start for a reason nothing on screen explains. */}
      {probe?.vita_release?.vita && !probe.vita_release.licence && (
        <PanelSectionRow>
          <Field
            label="No licence in this release"
            description="PS Vita releases normally carry a work.bin licence file. Without one the game installs but may refuse to start."
          />
        </PanelSectionRow>
      )}

      {pendingPackage && (
        <PanelSectionRow>
          {unpacking ? (
            <InstallProgress
              label={
                pendingPackage.system === "ps4"
                  ? "Installing into shadPS4"
                  : pendingPackage.system === "vita"
                    ? "Installing into Vita3K"
                    : "Installing into RPCS3"
              }
              percent={unpackPercent}
              status={unpackStatus}
            />
          ) : (
            <ButtonItem
              layout="below"
              onClick={() => unpackPackage(pendingPackage.system)}
              // Refused rather than allowed to fail: without the key Vita3K
              // reports a corrupt package, which reads as a bad download.
              disabled={adding || pendingPackage.state.licence === false}
              description={
                pendingPackage.system === "vita"
                  ? // Vita3K installs it itself, like RPCS3 — but it cannot
                    // decrypt without the key the package was sold with, and
                    // cannot work that out, so the key has to arrive too.
                    pendingPackage.state.licence === false
                    ? "No licence key found beside this package. Vita3K cannot decrypt one without it — send the game's .zrif or .txt to the same folder and it will be picked up."
                    : "Vita3K installs and decrypts this itself, with no window and nothing to press. The .pkg is deleted afterwards, using the licence key found beside it."
                  : pendingPackage.system === "ps4"
                  ? // shadPS4 cannot do this itself, so the first PS4 package
                    // fetches the extractor. Worth saying: it is the one thing
                    // here that downloads something the emulator did not bring.
                    "A PlayStation 4 package is not a game until it is unpacked. " +
                    "shadPS4 has no way to do that, so the first one fetches a " +
                    "small extractor built from shadPS4's own code. Large games " +
                    "take a while. The .pkg is deleted afterwards — the game is " +
                    "then installed and the package is never read again."
                  : "A PlayStation 3 package is not a game until RPCS3 unpacks it. " +
                    "This takes a few seconds, opens no windows, and deletes the .pkg " +
                    "afterwards — the game is then installed and the package is never " +
                    "read again. Store games also need their .rap licence, which " +
                    "goes in with the game if it was sent alongside it."
              }
            >
              {/* "Install", not "Unpack", on all three. Only RPCS3 and the PS4
                  extractor literally unpack anything -- Vita3K installs -- and
                  the word the user cares about is the same in every case: the
                  game ends up in the emulator. */}
              {`Install ${pendingPackage.state.title_id || "this package"}`}
            </ButtonItem>
          )}
        </PanelSectionRow>
      )}

      {probe && !pendingPackage && probe.matching_cores.length > 0 && (
        <>
          <PanelSectionRow>
            <DropdownItem
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

      {probe && !pendingPackage && probe.matching_cores.length === 0 && (
        <PanelSectionRow>
          <DropdownItem
            label="Run with"
            description={`Nothing installed claims .${probe.match_extension}`}
            rgOptions={coreOptions}
            selectedOption={coreId}
            onChange={onCoreChange}
            disabled={adding || coreOptions.length === 0}
          />
        </PanelSectionRow>
      )}

      {installable.length > 0 && (
        <>
          <PanelSectionRow>
            <Field
              label="No core installed for this ROM"
              description={`These cores can run .${probe?.match_extension} — install one to continue.`}
            />
          </PanelSectionRow>
          {installable.slice(0, 4).map((core) => (
            <PanelSectionRow key={core.id}>
              <ButtonItem
                layout="below"
                onClick={() => void installAndUse(core)}
                disabled={Boolean(installingCore) || adding}
              >
                {installingCore === core.id
                  ? `Installing ${core.display_name}...`
                  : `Install ${core.display_name}`}
              </ButtonItem>
            </PanelSectionRow>
          ))}
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
            {resolved?.art?.capsule ? "Wrong game? Pick artwork" : "Find artwork manually"}
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
