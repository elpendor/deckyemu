import {
  ConfirmModal,
  DialogButton,
  Field,
  PanelSection,
  PanelSectionRow,
} from "@decky/ui";
import { toaster } from "@decky/api";
import { useCallback, useEffect, useState } from "react";
import { FaCheckCircle, FaDownload, FaExclamationTriangle, FaTrash } from "react-icons/fa";

import {
  installHelperTool,
  removeHelperTool,
  toolsStatus,
  type HelperTool,
} from "./backend";
import { humanSize } from "./TransferModal";
import { callWithRetry } from "./timeout";
import { openModal } from "./modalStack";
import { ICON_BUTTON } from "./iconButton";
import { toolLine } from "./toolState";

/**
 * The helper binaries this plugin downloads, and whether they are here.
 *
 * **Its own section, next to BIOS and firmware rather than inside it.** That
 * list makes one promise and makes it plainly: everything on it is a dump from
 * the user's own hardware and is never downloaded. These are the inverse —
 * small programs fetched from other projects' releases because an emulator
 * cannot do something itself. Filing them together would have cost the firmware
 * section the only sentence that makes it unambiguous.
 *
 * **It exists because nothing said where these were.** The motion server was
 * fetched silently at startup, so a Deck where the download had been
 * rate-limited looked exactly like one where gyro was not a feature, and the
 * only way to tell was reading a plugin log over SSH.
 *
 * Only tools an installed emulator actually wants. A row for something nothing
 * needs yet is an invented chore — the same rule the firmware section follows.
 */
interface Props {
  /**
   * Changes when an emulator is installed or removed above.
   *
   * What belongs here is decided by which emulators are present, and that is
   * decided in a different panel — so without a nudge, installing Ryujinx would
   * add nothing here until the page was closed and reopened.
   */
  reloadKey?: number;
}

export function ToolsPanel({ reloadKey = 0 }: Props) {
  const [tools, setTools] = useState<HelperTool[]>([]);
  const [busy, setBusy] = useState("");

  const load = useCallback(() => {
    callWithRetry(toolsStatus)
      .then((report) => setTools(report.tools))
      // An empty section rather than an error: this sits under two panels that
      // work, and a failure to list helpers must not take them with it.
      .catch(() => setTools([]));
  }, []);

  useEffect(load, [load, reloadKey]);

  const install = useCallback(
    (tool: HelperTool) => {
      setBusy(tool.name);
      installHelperTool(tool.name)
        .then((result) => {
          if (!result.ok) {
            toaster.toast({ title: tool.label, body: result.error || "Could not download it." });
            return;
          }
          toaster.toast({ title: tool.label, body: "Installed." });
        })
        .catch((error: unknown) => {
          toaster.toast({ title: tool.label, body: String(error) });
        })
        .finally(() => {
          setBusy("");
          load();
        });
    },
    [load],
  );

  const remove = useCallback(
    (tool: HelperTool) => {
      openModal(
        <ConfirmModal
          strTitle={`Remove ${tool.label}?`}
          strOKButtonText="Remove"
          onOK={() => {
            setBusy(tool.name);
            removeHelperTool(tool.name)
              .then(load)
              .finally(() => setBusy(""));
          }}
          strDescription={
            /* What stops working, named. Removing a file whose absence is felt
               somewhere else entirely is the kind of thing to say before it is
               done rather than to discover in a game. */
            `${tool.needed_by.join(" and ")} will lose it until it is downloaded again. ` +
            `Nothing else is affected.`
          }
        />,
      );
    },
    [load],
  );

  const shown = tools.filter((tool) => tool.wanted);
  if (shown.length === 0) return null;

  return (
    <PanelSection title="Tools">
      {shown.map((tool) => {
        const Icon = tool.installed ? FaCheckCircle : FaExclamationTriangle;
        return (
          <PanelSectionRow key={tool.name}>
            <Field
              label={
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <Icon
                    style={{
                      color: tool.installed ? "#5ba32b" : "#e0a800",
                      flexShrink: 0,
                      fontSize: "15px",
                    }}
                  />
                  <span>{tool.label}</span>
                </div>
              }
              description={toolLine(tool, humanSize)}
              childrenContainerWidth="min"
            >
              <div style={{ display: "flex", gap: "6px" }}>
                {tool.installed ? (
                  <DialogButton
                    disabled={Boolean(busy)}
                    onClick={() => remove(tool)}
                    style={ICON_BUTTON}
                  >
                    <FaTrash />
                  </DialogButton>
                ) : (
                  <DialogButton
                    disabled={Boolean(busy)}
                    onClick={() => install(tool)}
                    style={ICON_BUTTON}
                  >
                    <FaDownload />
                  </DialogButton>
                )}
              </div>
            </Field>
          </PanelSectionRow>
        );
      })}
      <PanelSectionRow>
        {/* The counterpart of the firmware section's own line, and the reason
            these are two sections. Said once, under the list, rather than on
            every row. */}
        <Field
          description="Downloaded from each project's own releases, and used only by the emulator that needs it."
          focusable={false}
        />
      </PanelSectionRow>
    </PanelSection>
  );
}
