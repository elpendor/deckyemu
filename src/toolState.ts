import type { HelperTool } from "./backend/firmware";

/**
 * The description under a tool's name: what it is for, and where it stands.
 *
 * Its own module so it can be checked without dragging `@decky/ui` into a test
 * runner, which is the same reason `emulatorLegend` and `firmwareState` are not
 * inside their panels.
 *
 * **It always says where it stands, including when that is "here".** The first
 * version of this stayed quiet when the tool was installed, on the grounds that
 * a working thing needs no line — which made it useless for the one question it
 * was built to answer. Silence and success have to look different.
 */
export function toolLine(tool: HelperTool, size: (bytes: number) => string): string {
  const parts = [tool.why, `From ${tool.repo}.`];

  if (tool.installed) {
    parts.push(size(tool.size) ? `Installed, ${size(tool.size)}.` : "Installed.");
  } else if (tool.waiting > 0) {
    // A wait is not a failure. GitHub limits how often one address may ask and
    // clears on its own, so naming the wait turns "this is broken" into "this
    // is coming" — the distinction that cost a session of debugging.
    parts.push(`Waiting to retry, about ${Math.ceil(tool.waiting / 60)} min.`);
  } else {
    parts.push("Not downloaded yet.");
  }

  return parts.filter(Boolean).join(" ");
}
