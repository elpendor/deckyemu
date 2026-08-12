/**
 * What each button in the emulator list does, in words.
 *
 * The row carries up to seven different buttons depending on what state the
 * emulator is in, and each one is an icon alone. On a desktop these would be
 * tooltips; in Game Mode there is no pointer to hover with, so the meanings
 * have to live somewhere a thumbstick can reach.
 *
 * Data rather than JSX so the list can be checked: `emulatorLegend.test.ts`
 * reads the panel and fails if it renders an icon nothing here explains, which
 * is the way this goes stale -- a button added a year from now, in a state
 * nobody thinks about, silently unexplained.
 */

export interface LegendEntry {
  /** The react-icons name, which is what the panel renders and the test matches. */
  icon: string;
  /** What the button is called. */
  label: string;
  /** What it does, and when it shows up -- half the confusion is the latter. */
  detail: string;
}

export const EMULATOR_LEGEND: LegendEntry[] = [
  {
    icon: "FaDownload",
    label: "Install",
    detail: "Downloads and installs the emulator. Shown when it is not installed yet.",
  },
  {
    icon: "FaLink",
    label: "Set up for adding games",
    detail:
      "The emulator is already installed, but something else installed it, so this " +
      "plugin does not yet know it is there and your ROMs will not match it. This " +
      "connects the two. Nothing is downloaded and the existing install is untouched.",
  },
  {
    icon: "FaFolderOpen",
    label: "Point at the file",
    detail:
      "For emulators this plugin sets up but does not obtain, and to hand it a newer " +
      "build you downloaded yourself. Opens a file picker.",
  },
  {
    icon: "FaCodeBranch",
    label: "Version",
    detail:
      "Update, go back to an earlier build, or hold the current one so updates leave " +
      "it alone. Only for emulators whose build can actually be changed.",
  },
  {
    icon: "FaWindowMaximize",
    label: "Open the emulator",
    detail:
      "Launches the emulator's own interface, for settings this plugin does not cover. " +
      "It opens as a game, so the Steam button closes it.",
  },
  {
    icon: "FaTrash",
    label: "Uninstall",
    detail:
      "Removes the emulator from the Deck. Your ROMs, saves and BIOS files are left " +
      "alone. Greyed out for a system-wide install, which needs a password this plugin " +
      "cannot give.",
  },
  {
    icon: "FaEraser",
    label: "Forget",
    detail:
      "Removes the entry from this list without uninstalling anything. For emulator " +
      "definitions you imported, when you no longer want them offered.",
  },
];
