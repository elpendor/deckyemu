import {
  ConfirmModal,
  DialogButton,
  Field,
  PanelSection,
  PanelSectionRow,
} from "@decky/ui";
import {
  addEventListener,
  FileSelectionType,
  openFilePicker,
  removeEventListener,
  toaster,
} from "@decky/api";
import { useCallback, useEffect, useState } from "react";
import {
  FaDownload,
  FaFolderOpen,
  FaLink,
  FaEraser,
  FaCodeBranch,
  FaQuestion,
  FaTrash,
  FaWindowMaximize,
} from "react-icons/fa";

import { EmulatorLegendModal } from "./EmulatorLegendModal";

import {
  emulatorBuilds,
  getStatus,
  installEmulator,
  listEmulatorCatalog,
  locateEmulator,
  prepareEmulatorGui,
  registerEmulator,
  removeImportedEmulator,
  uninstallEmulator,
  type CatalogEmulator,
  type EmulatorBuild,
} from "./backend";
import { EmulatorVersionModal } from "./EmulatorVersionModal";
import { RemoveEmulatorModal } from "./RemoveEmulatorModal";
import { InstallProgress } from "./InstallProgress";
import { emulatorRowActions } from "./emulatorActions";
import { sourceLabel } from "./emulatorSource";
import { byName } from "./order";
import { openSetupShortcut } from "./setupShortcut";
import { callWithRetry } from "./timeout";
import { logError } from "./logError";
import { openModal } from "./modalStack";

interface Props {
  /** Re-read cores and emulators, so a new install becomes selectable. */
  onChanged: () => void;
}

const MUTED = { fontSize: "12px", opacity: 0.6 };

/**
 * The emulator's name with where its build comes from beside it.
 *
 * Small and parenthesised rather than another word in the description, because
 * it belongs to the name -- it is what distinguishes this listing of an
 * emulator from the same emulator obtained some other way -- and the
 * description is already three facts long on an installed row.
 */
function nameWithSource(entry: CatalogEmulator) {
  const source = sourceLabel(entry.kind);
  if (!source) return entry.name;
  /*
   * One element, with the gap inside the small half.
   *
   * Steam's `FieldLabelRow` is a flex container, and that breaks the obvious
   * version of this in two ways at once. A fragment of `{name} <span>` puts
   * three children in that flex box, and the whitespace one between them is an
   * anonymous flex item, which the spec drops -- so the name ran straight into
   * the bracket. The remaining two are then laid out by `align-items: center`,
   * which centres a 12px box against a 19px one instead of sitting them on a
   * shared baseline, so the source rode high or low depending on the row.
   *
   * Wrapped in one span, the label is a single flex item and everything inside
   * it is ordinary inline text again: the space survives and the baseline is
   * the one the name is on.
   */
  return (
    <span>
      {entry.name}
      <span style={MUTED}>{` (${source})`}</span>
    </span>
  );
}

/**
 * What the row says under the emulator's name.
 *
 * The extension list is the interesting part -- it is derived from libretro's
 * metadata rather than typed, so showing it is what makes it checkable.
 */
function describe(entry: CatalogEmulator, build?: EmulatorBuild): string {
  // A bring-your-own entry with nothing located yet: the plugin knows how to
  // run this emulator but will not obtain it, and the row would otherwise look
  // like an install that has not happened.
  if (entry.kind === "byo" && !entry.present) {
    return `${entry.system} · you supply the emulator, this sets it up`;
  }
  // Present but not registered is a real state, not an edge case: Discover and
  // the usual emulation setups install these same flatpaks, and one that arrived
  // that way has no extensions and never shows up when adding a game. Saying so
  // is the only clue the user gets about why their ROM matches nothing.
  if (entry.present && !entry.registered) {
    // Names the button as well as the state. Saying only what is wrong leaves
    // the fix to be inferred from a chain icon sitting next to it, which is the
    // one row where the thing to do is not obvious from the row.
    return `${entry.system} · installed elsewhere · press the link button to set it up`;
  }
  // The version state goes here rather than only inside the dialog, because
  // nothing would otherwise prompt anybody to open it. "Held" is the one that
  // most needs saying: a pinned emulator stops receiving updates indefinitely,
  // and an invisible pin is a trap rather than a feature.
  const version = build?.held
    ? "held at this build"
    : build?.update_available
      ? "update available"
      : "";

  const extensions = entry.extensions.map((extension) => `.${extension}`).join(" ");
  const parts = [entry.system, extensions, version].filter(Boolean);
  return parts.join(" · ");
}

export function EmulatorCatalogPanel({ onChanged }: Props) {
  const [entries, setEntries] = useState<CatalogEmulator[]>([]);
  const [loading, setLoading] = useState(true);
  // Which entry is installing, and how far along. Only one at a time: two
  // concurrent flatpak transactions block on each other's lock anyway.
  const [busyId, setBusyId] = useState("");
  /*
   * What the busy row is busy doing, e.g. "Removing PCSX2".
   *
   * Carried rather than hardcoded in the row, which said "Installing" whatever
   * was actually happening -- so registering, opening or removing an emulator
   * all claimed to be installing it if they got as far as drawing the bar.
   */
  const [busyLabel, setBusyLabel] = useState("");
  const [percent, setPercent] = useState(0);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [homeDir, setHomeDir] = useState("");
  // Which installed emulators can have their build changed, keyed by entry id.
  // Two flatpak queries for all of them, so it is cheap enough to read here and
  // saves the version dialog asking again for the row that opened it.
  const [builds, setBuilds] = useState<Record<string, EmulatorBuild>>({});

  const load = useCallback(() => {
    callWithRetry(listEmulatorCatalog)
      .then(setEntries)
      .catch((loadError) => logError("could not read the catalog", loadError))
      .finally(() => setLoading(false));
    // Separate call, and a failure here must not blank the catalog: not knowing
    // whether an update is waiting is a missing button, while not knowing what
    // is installed is an empty tab.
    callWithRetry(emulatorBuilds)
      .then((rows) =>
        setBuilds(Object.fromEntries(rows.map((row) => [row.id, row]))),
      )
      .catch((buildError) =>
        logError("could not read emulator builds", buildError),
      );
  }, []);

  // Where the "locate" picker starts. Read from the backend rather than
  // hardcoded, because the real home is not /home/deck on every install.
  useEffect(() => {
    callWithRetry(getStatus)
      .then((status) => setHomeDir(status.home_dir))
      .catch(() => undefined);
  }, []);

  useEffect(load, [load]);

  useEffect(() => {
    const onProgress = (_id: string, text: string, pct: number) => {
      setStatus(text.length > 110 ? `${text.slice(0, 107)}...` : text);
      if (pct >= 0) setPercent(Math.max(0, Math.min(100, pct)));
    };
    const onDone = (id: string, ok: boolean, message: string) => {
      setBusyId("");
      setPercent(0);
      setStatus("");
      const entry = entries.find((item) => item.id === id);
      if (ok) {
        toaster.toast({
          title: `${entry?.name ?? "Emulator"} installed`,
          // A notice here means it installed but could not be registered, which
          // is the one case where "installed" alone would be misleading.
          body: message || "It is ready to pick when you add a game.",
        });
        load();
        onChanged();
      } else {
        setError(message || "The install did not complete.");
      }
    };

    const progressListener = addEventListener<[id: string, text: string, percent: number]>(
      "emulator_install_progress",
      onProgress,
    );
    const doneListener = addEventListener<[id: string, ok: boolean, message: string]>(
      "emulator_install_done",
      onDone,
    );
    return () => {
      removeEventListener("emulator_install_progress", progressListener);
      removeEventListener("emulator_install_done", doneListener);
    };
  }, [entries, load, onChanged]);

  const start = useCallback(async (entry: CatalogEmulator) => {
    setBusyId(entry.id);
    setBusyLabel(`Installing ${entry.name}`);
    setError("");
    setPercent(0);
    setStatus("Starting...");
    try {
      const result = await installEmulator(entry.id);
      if (!result.ok) {
        setError(result.error ?? "Could not start the install.");
        setBusyId("");
      }
    } catch (startError) {
      logError("emulator install could not start", startError);
      setError("Could not start the install.");
      setBusyId("");
    }
  }, []);

  const confirmInstall = useCallback(
    (entry: CatalogEmulator) => {
      // Firmware is the honest part of this flow: the install gets you the
      // emulator, not necessarily a working system, and saying so before the
      // download beats a game that fails to boot afterwards.
      const needs = entry.firmware;
      if (needs.length === 0 && entry.verified && !entry.note) {
        void start(entry);
        return;
      }

      openModal(
        <ConfirmModal
          strTitle={`Install ${entry.name}?`}
          strOKButtonText="Install"
          onOK={() => void start(entry)}
          // Through strDescription rather than as children: it is typed as a
          // ReactNode and it is the form every other modal here already uses,
          // and @decky/ui's props are a description of Steam's components
          // rather than a contract worth testing on the device.
          strDescription={
            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              <div>
                {entry.kind === "flatpak"
                  ? "Installed from Flathub for your user — no password needed."
                  : "Downloaded from the project's own releases."}
              </div>

              {entry.note && <div style={MUTED}>{entry.note}</div>}

              {!entry.verified && (
                <div style={MUTED}>
                  Its launch arguments are a best reading of the documentation rather than
                  confirmed behaviour. If a game opens the emulator but not the game, edit
                  them under Custom emulators.
                </div>
              )}

              {needs.length > 0 && (
                <div>
                  <div style={{ marginBottom: "4px" }}>You will also need to supply:</div>
                  {needs.map((requirement) => (
                    <div key={requirement.name} style={{ marginBottom: "4px" }}>
                      <div>{requirement.name}</div>
                      <div style={MUTED}>{requirement.note}</div>
                    </div>
                  ))}
                  <div style={MUTED}>
                    These are your own dumps and are never downloaded by this plugin. Send
                    them over with Transfer once the emulator is installed.
                  </div>
                </div>
              )}
            </div>
          }
        />,
      );
    },
    [start],
  );

  // No confirmation: this only adds a registration, and the Remove button
  // beside it undoes the whole thing.
  const register = useCallback(
    (entry: CatalogEmulator) => {
      setBusyId(entry.id);
      setBusyLabel(`Setting up ${entry.name}`);
      setStatus(`Setting up ${entry.name}`);
      setPercent(-1);
      void (async () => {
        try {
          const result = await registerEmulator(entry.id);
          if (!result.ok) {
            toaster.toast({ title: "Could not set up", body: result.error ?? "" });
            return;
          }
          toaster.toast({
            title: `${entry.name} is ready`,
            body: `It can now be picked when adding a ${entry.system} game.`,
          });
          load();
          onChanged();
        } finally {
          setBusyId("");
          setStatus("");
        }
      })();
    },
    [load, onChanged],
  );

  // Opens the emulator's own interface as a Steam shortcut, then launches it.
  //
  // Through Steam rather than directly because gamescope only composites what
  // Steam started: run from the plugin, RPCS3's firmware installer opens a
  // dialog that is genuinely on screen in X and that nobody can ever see, and
  // waits for a click forever. This is the only route to the jobs an emulator
  // keeps behind its own windows.
  const openGui = useCallback(
    (entry: CatalogEmulator) => {
      setBusyId(entry.id);
      setBusyLabel(`Opening ${entry.name}`);
      setStatus(`Opening ${entry.name}`);
      setPercent(-1);
      void (async () => {
        try {
          const prepared = await prepareEmulatorGui(entry.id);
          if (!prepared.ok || !prepared.exe) {
            toaster.toast({ title: "Could not open", body: prepared.error ?? "" });
            return;
          }

          const appId = await openSetupShortcut({
            title: prepared.title ?? entry.name,
            exe: prepared.exe,
            start_dir: prepared.start_dir,
            app_id: prepared.app_id,
          });
          if (!appId) {
            toaster.toast({
              title: `Could not open ${entry.name}`,
              // The shortcut is hidden, so "find it in your library" would send
              // somebody looking somewhere it does not appear.
              body: `Steam would not start it. "${prepared.title}" is in your hidden games if you want to run it yourself.`,
            });
            return;
          }
          onChanged();
        } catch (openError) {
          logError("could not open the emulator", openError);
          toaster.toast({ title: "Could not open", body: `${openError}` });
        } finally {
          setBusyId("");
          setStatus("");
        }
      })();
    },
    [onChanged],
  );

  // Bring-your-own: the plugin supplies the recipe, the user supplies the
  // binary. openFilePicker *rejects* when the user backs out, so a cancel has
  // to be caught rather than read off the result.
  const locate = useCallback(
    (entry: CatalogEmulator) => {
      void (async () => {
        let picked;
        try {
          picked = await openFilePicker(
            FileSelectionType.FILE,
            homeDir || "/home/deck",
            true,
          );
        } catch {
          return;
        }
        if (!picked?.path) return;

        setBusyId(entry.id);
        setBusyLabel(`Setting up ${entry.name}`);
        setStatus(`Setting up ${entry.name}`);
        setPercent(-1);
        try {
          const result = await locateEmulator(entry.id, picked.path);
          if (!result.ok) {
            toaster.toast({ title: "Could not set up", body: result.error ?? "" });
            return;
          }
          toaster.toast({
            title: `${entry.name} is ready`,
            body: `It can now be picked when adding a ${entry.system} game.`,
          });
          load();
          onChanged();
        } finally {
          setBusyId("");
          setStatus("");
        }
      })();
    },
    [homeDir, load, onChanged],
  );

  // Removing an imported emulator means removing the definition, not
  // uninstalling anything: the binary is the user's and was never ours to
  // delete.
  const confirmForget = useCallback(
    (entry: CatalogEmulator) => {
      openModal(
        <ConfirmModal
          strTitle={entry.present && entry.kind !== "byo" ? `Remove ${entry.name}?` : `Forget ${entry.name}?`}
          strDescription={
            entry.present && entry.kind !== "byo"
              ? `This uninstalls ${entry.name} and removes the definition ` +
                `(${entry.source_file}). Both, because once the definition is gone ` +
                "there is no row left to uninstall it from. Games already added keep " +
                "their launcher scripts, and re-importing the file brings it all back."
              : `This removes the imported definition (${entry.source_file}) and its ` +
                "setup. Nothing is uninstalled — this plugin did not install anything " +
                "for it. Games already added keep their launcher scripts."
          }
          strOKButtonText="Forget"
          bDestructiveWarning
          onOK={() => {
            void (async () => {
              // The slowest of the three: this uninstalls the emulator before
              // deleting the definition, so it carries a whole flatpak or
              // AppImage removal behind one press.
              setBusyId(entry.id);
              setBusyLabel(`Removing ${entry.name}`);
              setStatus(`Removing ${entry.name}`);
              setPercent(-1);
              try {
                const result = await removeImportedEmulator(entry.id);
                if (!result.ok) {
                  toaster.toast({ title: "Could not remove", body: result.error ?? "" });
                  return;
                }
                toaster.toast({ title: "Definition removed", body: entry.name });
                load();
                onChanged();
              } finally {
                setBusyId("");
                setStatus("");
              }
            })();
          }}
        />,
      );
    },
    [load, onChanged],
  );

  const confirmRemove = useCallback(
    (entry: CatalogEmulator) => {
      openModal(
        // The dialog owns the question -- keep this emulator's data or not --
        // because the answer changes what it says, and the panel owns what
        // happens after, because that is the row that goes busy.
        <RemoveEmulatorModal
          emulator={entry}
          onConfirm={(deleteData) => {
            void (async () => {
              /*
               * Busy for the same reason installing is, and one that is not
               * cosmetic: without it the row looked idle for the seconds a
               * flatpak uninstall takes and its buttons stayed live, so Remove
               * could be pressed twice -- the second call failing with "not
               * installed" and reporting an error for something that had just
               * worked.
               *
               * No percentage, because flatpak reports none for a removal. The
               * bar travels instead, which is what "working, no idea how long"
               * looks like.
               */
              setBusyId(entry.id);
              setBusyLabel(`Removing ${entry.name}`);
              setStatus(`Removing ${entry.name}`);
              setPercent(-1);
              try {
                const result = await uninstallEmulator(entry.id, deleteData);
                if (!result.ok) {
                  toaster.toast({
                    title: "Could not remove emulator",
                    body: result.error ?? "",
                  });
                  return;
                }
                toaster.toast({
                  title: "Emulator removed",
                  body: deleteData ? `${entry.name}, with its data` : entry.name,
                });
                load();
                onChanged();
              } finally {
                // Cleared here rather than by an event: a removal is awaited
                // rather than streamed, so nothing else will ever clear it.
                setBusyId("");
                setStatus("");
              }
            })();
          }}
        />,
      );
    },
    [load, onChanged],
  );

  return (
    // Untitled section: SidebarNavigation already renders the tab's heading
    // above it. The name goes on the intro row instead, which had to exist
    // anyway -- and is needed there, because "Custom emulators" further down is
    // labelled, which left the larger list above it looking like the unnamed
    // preamble to it rather than the main thing on the tab.
    <PanelSection>
      <PanelSectionRow>
        <Field
          label="Ready-made emulators"
          // Ends by pointing down the page. Somebody looking for an emulator
          // that is not here has no reason to expect a second list further
          // down, and finding it by accident is how the two came to look like
          // rival lists rather than one leading into the other.
          description="For the systems RetroArch does not cover. The system, file types and launch arguments are all set up for you. Installing one also registers it below. Not here? Add your own there."
          childrenContainerWidth="min"
        >
          {/* Every button in the rows below is an icon on its own. On a desktop
              these would be tooltips; Game Mode has no pointer to hover with, so
              the meanings need a place a thumbstick can reach. Here, next to the
              heading, rather than a legend row per section -- one press for all
              of them, and no permanent block of text explaining buttons to
              somebody who already knows them. */}
          <DialogButton
            onClick={() => openModal(<EmulatorLegendModal />)}
            style={{ minWidth: "auto", width: "auto", padding: "6px 12px" }}
          >
            <FaQuestion />
          </DialogButton>
        </Field>
      </PanelSectionRow>

      {loading && (
        <PanelSectionRow>
          <Field label="Loading..." />
        </PanelSectionRow>
      )}

      {/* By name. The catalog's own order is the order entries were written
          into the file, which is no order at all to read down — and it is the
          list the firmware section below is compared against. */}
      {[...entries].sort(byName).map((entry) => {
        const actions = emulatorRowActions(entry);
        return (
        <PanelSectionRow key={entry.id}>
          {busyId === entry.id ? (
            /* The same Field as every other row, with the bar in the
               description. Replacing the row outright made the emulator's name
               jump to a different size and lose its inset, so an installing row
               read as a different kind of thing wedged into the list. */
            <Field
              label={nameWithSource(entry)}
              description={
                <InstallProgress
                  inline
                  label={busyLabel || `Working on ${entry.name}`}
                  percent={percent}
                  status={status}
                />
              }
            />
          ) : (
            <Field
              label={nameWithSource(entry)}
              description={describe(entry, builds[entry.id])}
              childrenContainerWidth="min"
            >
              <div style={{ display: "flex", gap: "6px" }}>
                {/* Installed elsewhere and never registered here: the only row
                    that would otherwise offer nothing but Remove, leaving no
                    way to make the emulator usable. */}
                {actions.register && (
                  <DialogButton
                    disabled={Boolean(busyId)}
                    onClick={() => register(entry)}
                    style={{ minWidth: "auto", width: "auto", padding: "6px 12px" }}
                  >
                    <FaLink />
                  </DialogButton>
                )}
                {/* Only for an emulator whose build can actually be moved --
                    a user-scope flatpak that is installed. Everything else is
                    absent rather than disabled: an AppImage has no published
                    history to choose from, and a system-scope flatpak would need
                    a password this plugin cannot give.

                    One button for four things (update, the list of earlier
                    builds, the hold and its release) because this row already
                    carries up to four of its own, and six small icons in a row
                    cannot be hit with a thumbstick. */}
                {builds[entry.id] && !builds[entry.id].reason && (
                  <DialogButton
                    disabled={Boolean(busyId)}
                    onClick={() =>
                      openModal(
                        <EmulatorVersionModal
                          emulator={builds[entry.id]}
                          onChanged={() => {
                            load();
                            onChanged();
                          }}
                        />,
                      )
                    }
                    style={{ minWidth: "auto", width: "auto", padding: "6px 12px" }}
                  >
                    <FaCodeBranch />
                  </DialogButton>
                )}
                {/* Registered installs only: opening the interface of an
                    emulator this plugin does not know about would give a
                    window with nothing behind it. */}
                {actions.gui && (
                  <DialogButton
                    disabled={Boolean(busyId)}
                    onClick={() => openGui(entry)}
                    style={{ minWidth: "auto", width: "auto", padding: "6px 12px" }}
                  >
                    <FaWindowMaximize />
                  </DialogButton>
                )}
                {/* Bring-your-own: there is nothing to download, so the
                    action is to point at the binary. Offered again once
                    located, because an AppImage the user replaced with a newer
                    build is the ordinary case rather than an error. */}
                {actions.locate && (
                  <DialogButton
                    disabled={Boolean(busyId)}
                    onClick={() => locate(entry)}
                    style={{ minWidth: "auto", width: "auto", padding: "6px 12px" }}
                  >
                    <FaFolderOpen />
                  </DialogButton>
                )}
                {/* Installing and forgetting are independent, and conflating
                    them cost a working button: while an imported entry was
                    always bring-your-own, "imported" and "installable" could
                    not both be true, so one chain served for both. Once an
                    imported definition could name a source, that chain reached
                    Forget first and the download button became unreachable --
                    the emulator looked un-installable with no way to say why.

                    Install/remove follows the source; Forget follows where the
                    definition came from. A bring-your-own entry has neither:
                    nothing to download, and the binary is the user's rather
                    than something this plugin put there and may take away. */}
                {(actions.install || actions.remove) &&
                  (actions.remove ? (
                    <DialogButton
                      // A system-wide flatpak belongs to root, so removal would
                      // hit a password prompt nothing here can answer.
                      disabled={Boolean(busyId) || entry.scope === "system"}
                      onClick={() => confirmRemove(entry)}
                      style={{ minWidth: "auto", width: "auto", padding: "6px 12px" }}
                    >
                      <FaTrash />
                    </DialogButton>
                  ) : (
                    <DialogButton
                      disabled={Boolean(busyId)}
                      onClick={() => confirmInstall(entry)}
                      style={{ minWidth: "auto", width: "auto", padding: "6px 12px" }}
                    >
                      <FaDownload />
                    </DialogButton>
                  ))}
                {actions.forget && (
                  <DialogButton
                    disabled={Boolean(busyId)}
                    onClick={() => confirmForget(entry)}
                    style={{ minWidth: "auto", width: "auto", padding: "6px 12px" }}
                  >
                    <FaEraser />
                  </DialogButton>
                )}
              </div>
            </Field>
          )}
        </PanelSectionRow>
        );
      })}

      {error && (
        <PanelSectionRow>
          <div style={{ color: "#e35d5d", fontSize: "13px", padding: "4px 0" }}>{error}</div>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}
