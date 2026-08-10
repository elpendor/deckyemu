import {
  ButtonItem,
  ConfirmModal,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  showModal,
  ToggleField,
  type SingleDropdownOption,
} from "@decky/ui";
import { toaster } from "@decky/api";
import { useCallback, useEffect, useState } from "react";

import {
  type Core,
  canUninstallRetroArch,
  emulatorBuilds,
  getSettings,
  listCores,
  realCores,
  setSettings,
  uninstallRetroArch,
  type EmulatorBuild,
  type PluginSettings,
  type RetroArchStatus,
} from "./backend";
import { AchievementsPanel } from "./AchievementsPanel";
import { CoreInstallPanel } from "./CoreInstallPanel";
import { DANGER_CLASS, DANGER_CSS } from "./danger";
import { EmulatorVersionModal } from "./EmulatorVersionModal";
import { InstallRetroArchPanel } from "./InstallRetroArchPanel";
import { callWithRetry } from "./timeout";

const HIDE_OSD_OPTIONS: SingleDropdownOption[] = [
  { data: "startup", label: "Hide the startup banner" },
  { data: "all", label: "Hide all on-screen messages" },
  { data: "keep", label: "Keep RetroArch's notifications" },
];

/**
 * Ordered by how likely each is to be wanted, not by RetroArch's own numbering:
 * the first three are what other Deck frontends bind, and the hold variants sit
 * near the bottom because they fire on a button games themselves use.
 */
const MENU_COMBO_OPTIONS: SingleDropdownOption[] = [
  { data: "start_select", label: "Select + Start" },
  { data: "l1_r1_start_select", label: "L1 + R1 + Select + Start" },
  { data: "l3_r3", label: "L3 + R3 (stick clicks)" },
  { data: "l1_r1", label: "L1 + R1" },
  { data: "l2_r2", label: "L2 + R2" },
  { data: "l3_r", label: "L3 + R" },
  { data: "down_select", label: "D-pad Down + Select" },
  { data: "down_y_l_r", label: "D-pad Down + Y + L1 + R1" },
  { data: "hold_start", label: "Hold Start" },
  { data: "hold_select", label: "Hold Select" },
  { data: "off", label: "Off - leave RetroArch's own setting" },
];

const HIDE_OSD_DESCRIPTIONS: Record<string, string> = {
  startup: "Suppresses the load animation and the notices that follow it.",
  all: "Also hides save-state confirmations and error messages.",
  keep: "RetroArch behaves exactly as it does on its own.",
};

/** The one thing every choice here must say, since it is easy to assume otherwise. */
const MENU_COMBO_SCOPE = "Applies to games run on a libretro core. Custom emulators are unaffected.";

const MENU_COMBO_OFF_DESCRIPTION =
  "Nothing is written, so whatever is in your retroarch.cfg applies. " +
  "On a Deck that usually means no controller shortcut at all -- Steam takes the Steam button before RetroArch can use it as Guide.";

const INSTALL_LABELS: Record<string, string> = {
  flatpak: "Flatpak",
  native: "Native package",
  appimage: "AppImage",
};

interface Props {
  status: RetroArchStatus;
  onRefresh: () => void;
  /** Passed straight through to the core list — see CoreInstallPanel. */
  reloadKey?: number;
}

/**
 * Everything about RetroArch itself: what is installed, which cores it has, and
 * how games launch into it.
 *
 * Ordered as the questions arrive rather than by where the code used to live:
 * what have I got, what can I add to it, and then how should it behave. The
 * launching options in particular were two tabs away from the thing they
 * configure, under a generic "Settings" heading.
 */
export function RetroArchPanel({ status, onRefresh, reloadKey = 0 }: Props) {
  const [settings, setLocalSettings] = useState<PluginSettings | null>(null);
  // Whether removal is even on offer, and why not when it is not. Asked of the
  // backend rather than guessed from `status.kind`, because a flatpak installed
  // system-wide looks identical from here and cannot be removed without root.
  const [removable, setRemovable] = useState<{ ok: boolean; reason?: string } | null>(null);
  const [removing, setRemoving] = useState(false);
  const [deleteData, setDeleteData] = useState(false);
  // What is actually installed. The core installer below is a picker -- it asks
  // which core you want, never says which you already have -- so without this
  // the only answer anywhere is a count.
  const [cores, setCores] = useState<Core[]>([]);

  useEffect(() => {
    callWithRetry(getSettings).then(setLocalSettings).catch(() => undefined);
  }, []);

  // Keyed on the count so Rescan, an install and a removal all refresh it.
  useEffect(() => {
    if (!status.found) {
      setCores([]);
      return;
    }
    callWithRetry(listCores)
      .then((all) => setCores(realCores(all)))
      .catch(() => undefined);
  }, [status.found, status.core_count]);

  useEffect(() => {
    if (!status.found) {
      setRemovable(null);
      return;
    }
    callWithRetry(canUninstallRetroArch)
      .then(setRemovable)
      .catch(() => setRemovable(null));
  }, [status.found, status.kind]);

  /*
   * Which build is installed, and whether a newer one is waiting.
   *
   * Read from the same endpoint the Emulators tab uses, under the reserved id
   * `retroarch` -- RetroArch is not in the catalog, but it is a Flathub app
   * installed the same way, so it is the same three operations on a different id.
   *
   * Absent for a native package or a loose AppImage, which is correct: neither
   * can be moved to another build from here. Keyed on `kind` as well as `found`
   * so reinstalling as a flatpak makes the section appear.
   */
  const [build, setBuild] = useState<EmulatorBuild | null>(null);
  const loadBuild = useCallback(() => {
    if (!status.found) {
      setBuild(null);
      return;
    }
    callWithRetry(emulatorBuilds)
      .then((rows) => setBuild(rows.find((row) => row.id === "retroarch") ?? null))
      .catch((error) => {
        console.error("[deckyemu] could not read the RetroArch build", error);
        setBuild(null);
      });
  }, [status.found]);

  useEffect(loadBuild, [loadBuild, status.kind]);

  const uninstall = useCallback(async () => {
    setRemoving(true);
    try {
      const result = await uninstallRetroArch(deleteData);
      if (!result.ok) {
        toaster.toast({
          title: "Could not remove RetroArch",
          body: result.error ?? "flatpak did not say why.",
        });
        return;
      }
      toaster.toast({
        title: "RetroArch removed",
        body: deleteData
          ? "Its configuration and saves went with it."
          : "Configuration and saves were kept.",
      });
      setDeleteData(false);
      onRefresh();
    } catch (error) {
      console.error("[deckyemu] uninstall failed", error);
      toaster.toast({
        title: "Could not remove RetroArch",
        body: "The backend did not answer. Check the plugin log.",
      });
    } finally {
      setRemoving(false);
    }
  }, [deleteData, onRefresh]);

  /**
   * Spell out the consequences before doing it, and vary them with the toggle.
   *
   * The part people do not expect is that added games survive: their shortcuts
   * and launchers stay exactly where they are and start working again the moment
   * RetroArch is reinstalled. Saying so is what stops this reading as "remove
   * everything I have set up".
   */
  const confirmUninstall = useCallback(() => {
    showModal(
      <ConfirmModal
        strTitle={deleteData ? "Uninstall RetroArch and delete its data?" : "Uninstall RetroArch?"}
        strDescription={
          "This removes the RetroArch flatpak that was installed for your user. " +
          (deleteData
            ? "Its configuration, saves, save states and every core downloaded into it are deleted with it, and none of that can be recovered. "
            : "Configuration, saves, save states and downloaded cores are kept, so reinstalling picks up where you left off. ") +
          "Games DeckyEmu added stay in your Steam library and keep their launchers, but they will not start until RetroArch is installed again. " +
          "Your ROM files are never touched."
        }
        strOKButtonText={deleteData ? "Uninstall and delete data" : "Uninstall RetroArch"}
        bDestructiveWarning
        onOK={() => void uninstall()}
      />,
    );
  }, [deleteData, uninstall]);

  const patch = useCallback(async (changes: Record<string, unknown>) => {
    try {
      setLocalSettings(await setSettings(changes));
    } catch (error) {
      console.error("[retroarch] failed to save settings", error);
    }
  }, []);

  /*
   * Nothing is installed yet, so this is the whole tab.
   *
   * Everything below the install would be furniture: cores cannot be downloaded
   * into an absent RetroArch, launch options configure something that cannot
   * launch, and removal is meaningless. Showing them anyway is what pushed the
   * one button that matters into third place, under a "Rescan" that only helps
   * someone who installed RetroArch by hand -- and the install panel offers its
   * own Rescan for exactly that case, so ours was a second copy.
   */
  if (!status.found) {
    return (
      <>
        {/* Untitled first: the sidebar already says "RetroArch", and a
            PanelSection title that repeats its tab prints the heading twice. */}
        <PanelSection>
          <PanelSectionRow>
            <Field
              label="Not detected"
              description="Install it below. If you would rather use something else, add a standalone emulator from the Emulators tab — cores and launch options appear here once RetroArch is installed."
            />
          </PanelSectionRow>
        </PanelSection>

        <InstallRetroArchPanel onInstalled={onRefresh} onRescan={onRefresh} />
      </>
    );
  }

  return (
    <>
      <style>{DANGER_CSS}</style>

      {/* Untitled: the sidebar already says "RetroArch", and a PanelSection
          title that repeats its tab prints the heading twice. The rows below
          carry their own labels, so nothing is lost. */}
      <PanelSection>
        <PanelSectionRow>
          <Field
            label={INSTALL_LABELS[status.kind] ?? status.kind}
            description={`${status.core_count} core(s) installed`}
          />
        </PanelSectionRow>

        {cores.length > 0 && (
          <PanelSectionRow>
            <Field
              label="Installed cores"
              description={cores.map((core) => core.short_name).join(" · ")}
            />
          </PanelSectionRow>
        )}

        <PanelSectionRow>
          <ButtonItem layout="below" onClick={onRefresh}>
            Rescan RetroArch and cores
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <CoreInstallPanel onCoresChanged={onRefresh} reloadKey={reloadKey} />

      {!settings ? (
        <PanelSection title="Launching">
          <PanelSectionRow>
            <Field label="Loading..." />
          </PanelSectionRow>
        </PanelSection>
      ) : (
        <PanelSection title="Launching">
          <PanelSectionRow>
            <DropdownItem
              label="RetroArch notifications"
              description={HIDE_OSD_DESCRIPTIONS[settings.hide_osd]}
              rgOptions={HIDE_OSD_OPTIONS}
              selectedOption={settings.hide_osd}
              onChange={(option) => void patch({ hide_osd: String(option.data) })}
            />
          </PanelSectionRow>

          <PanelSectionRow>
            <DropdownItem
              label="RetroArch menu shortcut"
              description={
                settings.menu_combo === "off"
                  ? MENU_COMBO_OFF_DESCRIPTION
                  : `Opens RetroArch's menu during a game. ${MENU_COMBO_SCOPE}`
              }
              rgOptions={MENU_COMBO_OPTIONS}
              selectedOption={settings.menu_combo}
              onChange={(option) => void patch({ menu_combo: String(option.data) })}
            />
          </PanelSectionRow>

          {/* The one row here that is not about RetroArch. It rides along because
              it answers the same question -- how does a game start -- and there is
              no other launching section to put it in. */}
          <PanelSectionRow>
            <ToggleField
              label="Launch custom emulators fullscreen"
              description="Applies each emulator's own fullscreen switch, set per emulator since none of them agree on one."
              checked={settings.emulator_fullscreen}
              onChange={(value) => void patch({ emulator_fullscreen: value })}
            />
          </PanelSectionRow>
        </PanelSection>
      )}

      {/* Above achievements and well above removal: this is maintenance you may
          actually want, and a version that broke something is the reason people
          reach for uninstall when they did not need to.

          Only for a user-scope flatpak. `reason` is non-empty for a system-wide
          one, and there is no row at all for a native package or an AppImage,
          because neither can be moved to a different build from here. Said out
          loud rather than left as a missing section -- the same rule the uninstall
          above follows. */}
      {status.found && build && (
        <PanelSection title="RetroArch version">
          <PanelSectionRow>
            <Field
              label={build.held ? "Held at this build" : "Installed build"}
              description={
                build.reason
                  ? build.reason
                  : build.held
                    ? `${build.build} — updates will not move it until you release the hold.`
                    : build.update_available
                      ? `${build.build} — a newer build is available.`
                      : `${build.build} — this is the newest build on Flathub.`
              }
            />
          </PanelSectionRow>

          {!build.reason && (
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                onClick={() =>
                  showModal(
                    <EmulatorVersionModal
                      emulator={build}
                      onChanged={() => {
                        loadBuild();
                        onRefresh();
                      }}
                    />,
                  )
                }
                description="Update, go back to an earlier build, or hold the one you have."
              >
                {build.update_available ? "Update or change version" : "Change version"}
              </ButtonItem>
            </PanelSectionRow>
          )}
        </PanelSection>
      )}

      <AchievementsPanel />

      {/* Last, and only once RetroArch is actually here. Removal is the one
          irreversible thing on this tab, so it sits below everything you would
          normally come here to do. */}
      {status.found && removable && (
        <PanelSection title="Remove RetroArch">
          {removable.ok ? (
            <>
              <PanelSectionRow>
                <ToggleField
                  label="Also delete saves and configuration"
                  description="Off: saves, save states, controller configs and downloaded cores are kept, and reinstalling picks up where you left off. On: all of it is deleted and cannot be recovered."
                  checked={deleteData}
                  onChange={setDeleteData}
                  disabled={removing}
                />
              </PanelSectionRow>

              <PanelSectionRow>
                <div className={DANGER_CLASS}>
                  <ButtonItem
                    layout="below"
                    onClick={confirmUninstall}
                    disabled={removing}
                    description="Removes the RetroArch flatpak installed for your user. Games DeckyEmu added stay in Steam and start working again if you reinstall it. ROM files are never touched. Asks first."
                  >
                    {removing ? "Removing..." : "Uninstall RetroArch"}
                  </ButtonItem>
                </div>
              </PanelSectionRow>
            </>
          ) : (
            // The reason, not a disabled button: every case here is something the
            // user can act on elsewhere, and none of them is a bug to report.
            <PanelSectionRow>
              <Field label="Cannot be removed from here" description={removable.reason} />
            </PanelSectionRow>
          )}
        </PanelSection>
      )}
    </>
  );
}
