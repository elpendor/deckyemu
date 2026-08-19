import type { CatalogEmulator } from "./backend";

/**
 * Where a ready-made emulator's build actually comes from.
 *
 * The row already says what the emulator runs and which files it takes, and
 * both of those are about the games. Where the build arrives from is a
 * different question and the one with consequences: a Flathub install is a
 * flatpak transaction that shares runtimes with everything else on the Deck and
 * updates with them, while a GitHub one is a single AppImage this plugin
 * downloads and keeps under ~/deckyemu/emulators. Two rows that look identical
 * behave differently when an install fails, when a build is held, and when
 * somebody goes looking for what is on disk.
 *
 * Empty for bring-your-own, because nothing is obtained at all -- the row's
 * own description already says the binary is the user's to supply, and
 * "(your own)" beside the name would only repeat it in fewer words.
 */
export function sourceLabel(kind: CatalogEmulator["kind"]): string {
  switch (kind) {
    case "flatpak":
      // The remote, not the packaging format: every install here adds the
      // flathub remote and pulls from it, so that is the honest answer to
      // "where did this come from".
      return "Flathub";
    case "github":
      return "GitHub";
    default:
      return "";
  }
}
