/**
 * How this build finishes an update the backend has downloaded and checked.
 * The service installs it beside the running version and restarts into it, so
 * there is nothing left for the panel to do.
 */

export interface Staged {
  version?: string;
  url?: string;
  sha256?: string;
}

export const updates = {
  /** Whether this window can install at all. */
  available: (): boolean => true,
  /** Under the install button, after "You are running ...". */
  how: "Installed beside this version, which stays as the one to go back to.",
  /** Under the install button when `available` is false. */
  unavailable: "",
  /** Where the update dot sits on our icon: inside the tab bar's corner. */
  dotOffset: "8px",
  /** When the backend could not be reached. */
  noAnswer: "The service did not answer.",
  /** Finish, and say what happened. */
  async finish(staged: Staged, version: string): Promise<{ title: string; body: string }> {
    return { title: `Installed ${staged.version ?? version}`, body: "DeckyEmu is restarting into it." };
  },
};
