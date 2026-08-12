/**
 * Hand an update to decky's own installer.
 *
 * The backend only finds releases. It runs as `deck` and the plugin directory is
 * root-owned, so it cannot replace itself. Decky's loader runs as root and already
 * knows how to download a plugin zip, check it, unpack it and reload -- including
 * its own confirmation dialog with a progress bar. So the whole install is one
 * call into decky rather than anything of ours.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

/** Decky's PluginInstallType, from its backend enums. */
export const enum InstallType {
  Reinstall = 1,
  Update = 2,
  Downgrade = 3,
}

interface DeckyBackend {
  call: (route: string, ...args: unknown[]) => Promise<unknown>;
}

/**
 * Decky's global websocket router.
 *
 * `call` from `@decky/api` is scoped to this plugin's own methods and cannot reach
 * `utilities/*`, so the global router is the only way in.
 *
 * In Game Mode the Quick Access panel renders inside a popup window that Big
 * Picture opened, and `DeckyBackend` lives on the window that created the document
 * -- not on the popup. Without the `opener` fallback the update button does
 * nothing in Game Mode while working perfectly in Desktop Mode, which is a
 * miserable thing to debug. (Credit to unifideck, whose source says it went
 * unnoticed for exactly that reason.)
 */
function deckyBackend(): DeckyBackend | null {
  const scope = window as any;
  return scope.DeckyBackend ?? scope.opener?.DeckyBackend ?? null;
}

export function canInstallUpdates(): boolean {
  return Boolean(deckyBackend()?.call);
}

/**
 * Ask decky to install a release.
 *
 * Returns once decky has *accepted* the request: it then shows its own confirm
 * dialog and does the work. So a resolved promise means "decky was asked", not
 * "the update is installed".
 */
export async function installUpdate(
  assetUrl: string,
  version: string,
  sha256 = "",
  installType: InstallType = InstallType.Update,
): Promise<void> {
  const backend = deckyBackend();
  if (!backend?.call) {
    throw new Error("Decky's installer is not reachable from this window.");
  }
  // Argument order matches decky's utilities/install_plugin route.
  await backend.call("utilities/install_plugin", assetUrl, "DeckyEmu", version, sha256, installType);
}
