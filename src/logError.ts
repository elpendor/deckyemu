import { logFrontendError } from "./backend";

/**
 * Report a frontend failure somewhere it can actually be read.
 *
 * The two halves of this plugin fail into different places and only one of them
 * is reachable. A backend exception lands in the plugin log and names its own
 * method; a frontend one goes to a CEF console that needs a second machine, an
 * IP address and a port to open — so in Game Mode nobody sees it, including the
 * person it happened to and the person they are reporting it to.
 *
 * This writes to both: the console, which is where a developer with a debugger
 * attached looks, and the plugin log, which is what a diagnostic report carries
 * and therefore what reaches a bug report.
 *
 * Use it instead of a bare `console.error` wherever the failure is something a
 * user could notice — a call that did not come back, an action that did
 * nothing. Not for a value that was merely absent, which is ordinary.
 */
export function logError(where: string, error: unknown, detail?: string): void {
  // The console first and always, so a failure to report the failure still
  // leaves the original where a debugger can see it.
  console.error(`[deckyemu] ${where}`, error, detail ?? "");

  try {
    void logFrontendError(where, describe(error), detail ?? "").catch(() => undefined);
  } catch {
    // Reporting is best effort by definition: the backend may be mid-reload,
    // which is one of the reasons a call fails in the first place. Throwing
    // here would turn a logged problem into an unlogged one.
  }
}

/**
 * An error as one line of text.
 *
 * Anything can be thrown, and the log is worth more than a `[object Object]`:
 * a rejected `callable` comes back as a string, decky returns a Python
 * traceback as one, and a genuine Error has a name and a message.
 */
function describe(error: unknown): string {
  if (error instanceof Error) return `${error.name}: ${error.message}`;
  if (typeof error === "string") return error;
  try {
    return JSON.stringify(error) ?? String(error);
  } catch {
    return String(error);
  }
}
