import { type BlockedState } from "./backend";

/**
 * What the panel says when the backend stays off, or null when it is on.
 *
 * Pure, like deviceGate, so each case is a test. The other build names itself
 * in the lock it holds; this side only repeats it.
 */
export interface BlockScreen {
  title: string;
  body: string;
}

export function blockScreen(blocked: BlockedState | undefined): BlockScreen | null {
  if (!blocked) return null;
  if (blocked.reason === "format") {
    return {
      title: "Update DeckyEmu",
      body:
        "Your games and settings were last saved by a newer DeckyEmu. " +
        "This version could misread them, so it stays off until it is updated.",
    };
  }
  if (blocked.reason === "switched") {
    const which = [blocked.build || "Another DeckyEmu", blocked.version].filter(Boolean).join(" ");
    return {
      title: "DeckyEmu is in use elsewhere",
      body:
        `${which} is the one in use, with the same games and settings, so this one stays off. ` +
        "Its tab appears once Steam restarts.",
    };
  }
  if (blocked.reason === "running") {
    const who = [blocked.build || "Another DeckyEmu", blocked.version].filter(Boolean).join(" ");
    return {
      title: "DeckyEmu is already running",
      body:
        `${who} is running and using the same games and settings. ` +
        "Two at once would overwrite each other's changes, so this one stays off. " +
        "Uninstall the one you don't want, then open this panel again.",
    };
  }
  return {
    title: "DeckyEmu is off",
    body: "This version could not safely use your games and settings, so it stays off.",
  };
}
