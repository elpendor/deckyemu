import {
  ConfirmModal,
  DialogButton,
  Field,
  PanelSection,
  PanelSectionRow,
  showModal,
} from "@decky/ui";
import { toaster } from "@decky/api";
import { useCallback, useEffect, useState } from "react";
import { FaCheckCircle, FaDownload, FaExclamationTriangle, FaTrash, FaUpload } from "react-icons/fa";

import {
  firmwareState,
  STATE_COLOR,
  STATE_TITLE,
  worstState,
  type FirmwareRowState,
} from "./firmwareState";

import {
  deleteFirmware,
  fetchFirmware,
  firmwareStatus,
  installFirmware,
  prepareFirmwareGui,
  uninstallFirmware,
  type FirmwareReport,
  type FirmwareState,
} from "./backend";
import { openSetupShortcut } from "./setupShortcut";
import { humanSize, TransferModal } from "./TransferModal";
import { callWithRetry } from "./timeout";
import { byName } from "./order";


/** The tick or the triangle, in the colour that state is drawn in. */
function StatusIcon({ state }: { state: FirmwareRowState }) {
  const Icon = state === "installed" ? FaCheckCircle : FaExclamationTriangle;
  return (
    <Icon
      title={STATE_TITLE[state]}
      style={{ color: STATE_COLOR[state], flexShrink: 0, fontSize: "15px" }}
    />
  );
}

/**
 * BIOS files and keys the user has to supply.
 *
 * Only emulators that are installed appear here — firmware for something not
 * installed is noise, and its destination folder would not exist to check.
 *
 * The section is deliberately blunt about the one thing this plugin cannot do:
 * these are dumps from the user's own hardware, so nothing is ever downloaded.
 * What it can do is remove every step after that — the file arrives over the
 * transfer flow and is put where the emulator reads it, with no file manager.
 */
interface Props {
  /**
   * Changes whenever an emulator is installed, removed or registered above.
   *
   * What belongs in this section is decided entirely by which emulators are
   * present, and that is decided in a different panel — so without a nudge,
   * installing RPCS3 added nothing here until the settings page was closed and
   * reopened. Which reads as the firmware step not existing.
   */
  reloadKey?: number;
}

export function FirmwarePanel({ reloadKey = 0 }: Props) {
  const [report, setReport] = useState<FirmwareReport | null>(null);
  const [busy, setBusy] = useState("");

  const load = useCallback(() => {
    callWithRetry(firmwareStatus)
      .then(setReport)
      .catch((error) => console.error("[deckyemu] could not read firmware status", error));
  }, []);

  useEffect(load, [load, reloadKey]);

  // Opened from the row that needs the file, so the dialog can say which one it
  // is waiting for; a single button at the bottom had no idea which of four
  // requirements the user was about to satisfy. Re-reads on dismiss, since the
  // point is that an arriving file turns "still needed" into "ready".
  const send = useCallback(
    (emulatorName: string, requirement: FirmwareState) => {
      showModal(
        <TransferModal
          purpose="firmware"
          onClosed={load}
          expecting={[
            {
              label: `${emulatorName} — ${requirement.name}`,
              expects: requirement.expects || requirement.note,
            },
          ]}
        />,
      );
    },
    [load],
  );

  const install = useCallback(
    (entryId: string, requirement: FirmwareState) => {
      setBusy(`${entryId}/${requirement.name}`);
      void (async () => {
        try {
          const result = await installFirmware(entryId, requirement.name);
          if (!result.ok) {
            toaster.toast({ title: "Could not install", body: result.error ?? "" });
            return;
          }
          const moved = result.copied?.length ?? 0;
          const kept = result.kept?.length ?? 0;
          toaster.toast({
            title: `${requirement.name} installed`,
            // An imported requirement was unpacked rather than copied, so what
            // to report is what the emulator produced — and that the file it
            // was given has been deleted, which the user would otherwise find
            // out by looking for it.
            body: requirement.imported
              ? `${(result.installed ?? []).join(", ")} is installed.` +
                (result.deleted?.length ? ` ${result.deleted.join(", ")} is no longer needed and has been deleted.` : "")
              : kept
                ? `${moved} file(s) moved into place; ${kept} already there and left alone.`
                : `${moved} file(s) moved into place.`,
          });
          load();
        } finally {
          setBusy("");
        }
      })();
    },
    [load],
  );

  /**
   * The one prerequisite this plugin fetches rather than asks for.
   *
   * Everything else here is a dump from the user's own hardware and is never
   * downloaded — that is the whole reason the transfer flow exists. xemu's
   * hard disk image is an empty formatted disk published by xemu's own
   * project, and without it xemu will not start at all, so the alternative is
   * telling somebody in Game Mode to go and find a zip.
   */
  const fetchIt = useCallback(
    (entryId: string, requirement: FirmwareState) => {
      setBusy(`${entryId}/${requirement.name}`);
      void (async () => {
        try {
          const result = await fetchFirmware(entryId, requirement.name);
          if (!result.ok) {
            toaster.toast({ title: "Could not download", body: result.error ?? "" });
            return;
          }
          toaster.toast({
            title: `${requirement.name} ready`,
            // Naming the setting is the point: the file being on disk is not
            // the same as the emulator knowing where it is.
            body: result.configured
              ? `Downloaded, and ${result.configured} now points at it.`
              : result.config_error || "Downloaded.",
          });
          load();
        } finally {
          setBusy("");
        }
      })();
    },
    [load],
  );

  /**
   * Hands the file to the emulator's own window, for the one requirement that
   * has no other route.
   *
   * Ryujinx reads `--install-firmware` inside its main window and then waits on
   * a Yes/No dialog, so neither the window nor the press can be removed — and a
   * window is only ever drawn if Steam launched it, which is why this goes out
   * through a shortcut rather than being run from here.
   */
  const guiInstall = useCallback(
    (entryId: string, emulatorName: string, requirement: FirmwareState) => {
      const key = `${entryId}/${requirement.name}`;
      setBusy(key);
      void (async () => {
        try {
          const prepared = await prepareFirmwareGui(entryId, requirement.name);
          if (!prepared.ok || !prepared.exe) {
            toaster.toast({ title: "Could not open", body: prepared.error ?? "" });
            return;
          }

          // The one setup shortcut, repointed at the script that was just
          // written to carry the install argument.
          const appId = await openSetupShortcut({
            title: prepared.title ?? emulatorName,
            exe: prepared.exe,
            start_dir: prepared.start_dir,
            app_id: prepared.app_id,
          });
          if (!appId) {
            toaster.toast({
              title: `Could not open ${emulatorName}`,
              // Hidden, so pointing at "your library" would send somebody
              // looking where it does not appear.
              body: `Steam would not start it. "${prepared.title}" is in your hidden games if you want to run it yourself.`,
            });
            return;
          }

          toaster.toast({
            title: `${emulatorName} is opening`,
            body: requirement.prompt || `${prepared.file} is ready to install.`,
          });
        } finally {
          setBusy("");
        }
      })();
    },
    [],
  );

  /**
   * Throws away a file that has already been imported.
   *
   * An imported requirement — RPCS3's firmware, Vita3K's — is unpacked by the
   * emulator rather than moved, so the .PUP it came from stays in the transfer
   * folder afterwards, doing nothing at two hundred megabytes. It also made the
   * row offer to install what was already installed, since a file waiting is
   * how "there is something to install" is decided.
   */
  const discard = useCallback(
    (requirement: FirmwareState) => {
      const key = `discard/${requirement.name}`;
      setBusy(key);
      void (async () => {
        try {
          const result = await deleteFirmware(requirement.waiting);
          if (!result.ok) {
            toaster.toast({ title: "Could not delete", body: result.error ?? "" });
            return;
          }
          toaster.toast({
            title: "Deleted",
            body: `${(result.removed ?? []).join(", ")} was already unpacked and is no longer needed.`,
          });
          load();
        } finally {
          setBusy("");
        }
      })();
    },
    [load],
  );

  // Deletes. Installing moved the file rather than copying it, so there is no
  // second copy and this is the end of it — which is not what a trash button
  // next to "In place" implies on its own, so the dialog says it outright.
  const confirmUninstall = useCallback(
    (entryId: string, emulatorName: string, requirement: FirmwareState) => {
      const foreign = requirement.foreign.length;
      showModal(
        <ConfirmModal
          strTitle={`Remove ${requirement.name} from ${emulatorName}?`}
          strDescription={
            requirement.tree
              ? // Nothing was copied here, so there is no "you would have to
                // send it again". What the user is agreeing to is deleting
                // everything the emulator wrote, which is the only way back to
                // a firmware that installed badly — so it is worth offering,
                // and worth being plain about.
                `Everything ${emulatorName} unpacked from it will be deleted. ` +
                `Games and saves are kept — they are stored elsewhere. ` +
                (requirement.manual
                  ? // Ryujinx installs its own, so putting it back is not a
                    // button here and saying which step it is beats "install
                    // it again" from a panel that cannot.
                    requirement.manual
                  : requirement.fetchable
                    ? "Installing it again is one press: it is downloaded, not sent."
                    : "Installing it again means sending the file from another device.")
              : `${requirement.installed.join(", ")} will be deleted from ${requirement.dest}. ` +
                "There is no other copy — installing moved it — so you would have to send it " +
                "from another device again. " +
                (foreign
                  ? `${foreign} of these was not put there by DeckyEmu, so it may be a file you placed yourself. `
                  : "")
          }
          strOKButtonText="Remove"
          bDestructiveWarning
          onOK={() => {
            void (async () => {
              const result = await uninstallFirmware(entryId, requirement.name);
              if (!result.ok) {
                toaster.toast({ title: "Could not remove", body: result.error ?? "" });
                return;
              }
              toaster.toast({
                title: `${requirement.name} removed`,
                body: result.freed
                  ? `${humanSize(result.freed)} recovered.`
                  : `${(result.removed?.length ?? 0) + (result.foreign?.length ?? 0)} file(s) deleted.`,
              });
              load();
            })();
          }}
        />,
      );
    },
    [load],
  );

  // Nothing installed that wants firmware: say nothing at all rather than
  // showing an empty section.
  if (!report || report.emulators.length === 0) return null;

  /* Waiting and missing share the triangle as well as the colour: both mean
     this requirement is not met yet, and the row's own words say which of the
     two it is and what to press. A third symbol would be a thing to learn for a
     distinction already spelled out an inch to the right. */

  return (
    <PanelSection title="BIOS and firmware">
      <PanelSectionRow>
        <Field description="Some systems need files only you can supply. They are never downloaded by this plugin — send one from another device and it is put where the emulator reads it." />
      </PanelSectionRow>

      {/* Grouped under the emulator, and in the same order as every other list
          of emulators in the plugin. Three of these ask for more than one file
          — xemu wants two dumps and a disk image — and repeating "xemu — " on
          every row spent the front of each label saying what the row above had
          already said. */}
      {[...report.emulators].sort(byName).map((emulator) => (
        <div key={emulator.id}>
          <PanelSectionRow>
            {/* The emulator's own line answers "does this one need me?" without
                reading any of its rows -- which is the question being asked when
                somebody scrolls past four emulators looking for the one that
                will not boot. */}
            <div
              style={{
                fontWeight: 600,
                padding: "10px 0 2px",
                display: "flex",
                alignItems: "center",
                gap: "8px",
              }}
            >
              <StatusIcon state={worstState(emulator.requirements)} />
              {emulator.name}
            </div>
          </PanelSectionRow>

          {emulator.requirements.map((requirement) => {
            const key = `${emulator.id}/${requirement.name}`;
            const ready = requirement.waiting.length > 0;
            const done = requirement.installed.length > 0;

            // A requirement the emulator has to import itself never gets a
            // button, so the arrival of the file must not read as "ready" — the
            // remaining step is still the user's, and saying which one is the
            // whole value of detecting the file at all.
            // Until a file turns up, the naming rule is the useful thing to
            // say: matching is on the filename, so a dump under any other name
            // is never recognised and nothing would explain why.
            let description: string;
            if (done) {
              // An imported requirement reports what the emulator produced —
              // RPCS3 says "4.93" — rather than which file was copied, because
              // no file was.
              description = requirement.detected
                ? // Read from a folder the emulator filled, so there is no
                  // filename or version to quote — only that it is there.
                  `Installed by ${emulator.name}.`
                : requirement.imported
                  ? `Installed: ${requirement.installed.join(", ")}`
                  : `In place: ${requirement.installed.join(", ")}`;
              // The file it was unpacked from is still sitting in the transfer
              // folder, because importing reads it rather than moving it. Said
              // here because a couple of hundred megabytes of it is worth
              // knowing about, and the bin next to this row is the way out.
              if (ready && (requirement.imported || requirement.detected)) {
                description += `. ${requirement.waiting.join(", ")} is still in the transfer folder and no longer needed`;
              }
            } else if (requirement.manual) {
              description = ready
                ? `${requirement.waiting.join(", ")} is here. ${requirement.manual}`
                : [requirement.manual, requirement.expects].filter(Boolean).join(" ");
            } else if (ready) {
              description = requirement.imported
                ? `Ready: ${requirement.waiting.join(", ")}. ${emulator.name} unpacks it itself — a few seconds, nothing to press.`
                : `Ready to install: ${requirement.waiting.join(", ")}`;
            } else {
              description = [requirement.note, requirement.expects]
                .filter(Boolean)
                .join(" ");
            }

            return (
              <PanelSectionRow key={key}>
                <Field
                  label={
                    <span style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <StatusIcon state={firmwareState(requirement)} />
                      {requirement.name}
                    </span>
                  }
                  description={description}
                  childrenContainerWidth="min"
                >
                  {/* One action per state: nothing sent yet means send it, a
                      file waiting means install it, and installed means take it
                      out again. The one row that offers two is an imported
                      requirement with its source file still lying about — the
                      firmware and the .PUP it came from are different things in
                      different places, and either can go without the other. */}
                  <div style={{ display: "flex", gap: "6px" }}>
                    {/* Installed decides first. It used to be `done &&
                        can_remove`, so an imported requirement fell through to
                        the next branch and offered to install what was already
                        installed, purely because the .PUP it was unpacked from
                        had not been cleaned up. The row said "Installed: 4.93"
                        and had an Install button on it. */}
                    {done ? (
                      <>
                        {ready && (requirement.imported || requirement.detected) && (
                          // Not the firmware — the file it was unpacked from,
                          // still in the transfer folder because importing
                          // reads it rather than moving it. Imported only: for
                          // a copied requirement a waiting file is a second
                          // dump the user may well want installed, not litter.
                          <DialogButton
                            disabled={busy === `discard/${requirement.name}`}
                            onClick={() => discard(requirement)}
                            style={{ minWidth: "auto", width: "auto", padding: "6px 12px" }}
                          >
                            Delete file
                          </DialogButton>
                        )}
                        {requirement.can_remove && (
                          <DialogButton
                            disabled={busy === key}
                            onClick={() =>
                              confirmUninstall(emulator.id, emulator.name, requirement)
                            }
                            style={{ minWidth: "auto", width: "auto", padding: "6px 12px" }}
                          >
                            <FaTrash />
                          </DialogButton>
                        )}
                      </>
                    ) : ready && requirement.can_install ? (
                      // Same button either way. Whether the file is moved into
                      // place, unpacked by the emulator unattended, or handed
                      // to its window to confirm is the emulator's business,
                      // not something to make the user hold in their head.
                      <DialogButton
                        disabled={busy === key}
                        onClick={() =>
                          requirement.gui_install
                            ? guiInstall(emulator.id, emulator.name, requirement)
                            : install(emulator.id, requirement)
                        }
                        style={{ minWidth: "auto", width: "auto", padding: "6px 12px" }}
                      >
                        Install
                      </DialogButton>
                    ) : requirement.can_fetch ? (
                      // Before the send button, because this one needs nothing
                      // from the user at all.
                      <DialogButton
                        disabled={busy === key}
                        onClick={() => fetchIt(emulator.id, requirement)}
                        style={{ minWidth: "auto", width: "auto", padding: "6px 12px" }}
                      >
                        <FaDownload />
                      </DialogButton>
                    ) : (
                      <DialogButton
                        disabled={busy === key}
                        onClick={() => send(emulator.name, requirement)}
                        style={{ minWidth: "auto", width: "auto", padding: "6px 12px" }}
                      >
                        <FaUpload />
                      </DialogButton>
                    )}
                  </div>
                </Field>
              </PanelSectionRow>
            );
          })}
        </div>
      ))}
    </PanelSection>
  );
}
