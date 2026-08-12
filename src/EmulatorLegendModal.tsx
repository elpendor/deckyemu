import { ModalRoot } from "@decky/ui";
import {
  FaCodeBranch,
  FaDownload,
  FaEraser,
  FaFolderOpen,
  FaLink,
  FaTrash,
  FaWindowMaximize,
} from "react-icons/fa";

import { EMULATOR_LEGEND } from "./emulatorLegend";

/**
 * What every button in the emulator list means.
 *
 * The buttons are icons alone -- there is no room in the row for words, and
 * six labelled buttons could not be hit with a thumbstick anyway. On a desktop
 * the answer would be a tooltip, but Game Mode has no pointer to hover with, so
 * the meanings need somewhere reachable instead. This is that place.
 *
 * The wording lives in `emulatorLegend`, as data, so a test can hold it against
 * the panel and fail when an icon appears that nothing here explains.
 */

/** The rendered icon for each entry, by the name the legend stores. */
const ICONS: Record<string, React.ReactNode> = {
  FaDownload: <FaDownload />,
  FaLink: <FaLink />,
  FaFolderOpen: <FaFolderOpen />,
  FaCodeBranch: <FaCodeBranch />,
  FaWindowMaximize: <FaWindowMaximize />,
  FaTrash: <FaTrash />,
  FaEraser: <FaEraser />,
};

interface Props {
  closeModal?: () => void;
}

export function EmulatorLegendModal({ closeModal }: Props) {
  return (
    <ModalRoot closeModal={closeModal}>
      <h1 style={{ marginTop: 0, marginBottom: "4px", fontSize: "23px" }}>
        The buttons in this list
      </h1>
      <div style={{ opacity: 0.7, fontSize: "13px", marginBottom: "16px" }}>
        Which ones a row shows depends on what state that emulator is in, so no
        row has all of them.
      </div>

      {EMULATOR_LEGEND.map((entry) => (
        <div
          key={entry.icon}
          style={{
            display: "flex",
            gap: "14px",
            alignItems: "flex-start",
            padding: "10px 0",
            // A rule between rows rather than around each: seven boxes read as a
            // form to fill in, where this is a list to read once.
            borderTop: "1px solid rgba(255, 255, 255, 0.1)",
          }}
        >
          <div
            style={{
              // Fixed width so the labels line up regardless of icon shape --
              // a ragged left edge makes seven short rows hard to scan.
              width: "24px",
              flexShrink: 0,
              textAlign: "center",
              fontSize: "18px",
              paddingTop: "2px",
            }}
          >
            {ICONS[entry.icon]}
          </div>
          <div>
            <div style={{ fontWeight: 600 }}>{entry.label}</div>
            <div style={{ opacity: 0.75, fontSize: "13px", lineHeight: 1.4 }}>{entry.detail}</div>
          </div>
        </div>
      ))}
    </ModalRoot>
  );
}
