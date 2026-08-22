import { ConfirmModal } from "@decky/ui";
import { toaster } from "@decky/api";

import { importEmulatorDefinition, previewEmulatorDefinition } from "./backend";
import { DANGER_CLASS } from "./danger";
import { openModal } from "./modalStack";

/**
 * Importing an emulator definition: read it, show what it will do, then store it.
 *
 * Out here because there are two ways in and they must not diverge. The
 * transfer dialog offers it on a file that has just arrived; the Emulators tab
 * offers it on anything sitting in the transfer folder, including a file sent
 * before the last reload. Both have to show the same warning, because the
 * warning is the feature.
 *
 * **The preview runs the same parse the import does.** A preview produced by
 * different code could describe something other than what happens, which would
 * be worse than showing nothing at all: the whole point is that somebody sees
 * what a file will install and where it may write *before* agreeing to it.
 */

const COLUMN = { display: "flex", flexDirection: "column" as const, gap: "8px" };
const MUTED = { fontSize: "13px", opacity: 0.7 };

/**
 * Preview `name`, ask, and import it if the user agrees.
 *
 * `onImported` is for the list that opened this. The catalog itself reloads on
 * its own -- the backend emits when it changes, so a list open somewhere else
 * hears about it too -- and this is only for the caller's own state.
 */
export function importDefinition(name: string, onImported?: () => void): void {
  void (async () => {
    const preview = await previewEmulatorDefinition(name);
    if (!preview.ok) {
      // Multi-line on purpose: a refused definition is refused per rule, and
      // the rules are what tell the author what to change.
      toaster.toast({ title: "Could not import", body: preview.error ?? "" });
      return;
    }

    const go = () =>
      void (async () => {
        const result = await importEmulatorDefinition(name, preview.replaces);
        if (!result.ok) {
          toaster.toast({ title: "Could not import", body: result.error ?? "" });
          return;
        }
        toaster.toast({
          title: `${result.name} imported`,
          body: preview.installs
            ? "Find it under Emulators and press install."
            : "Find it under Emulators and point it at the binary.",
        });
        onImported?.();
      })();

    openModal(
      <ConfirmModal
        strTitle={preview.replaces ? `Replace ${preview.name}?` : `Import ${preview.name}?`}
        strOKButtonText={preview.replaces ? "Replace" : "Import"}
        onOK={go}
        strDescription={
          <div style={{ ...COLUMN, gap: "10px" }}>
            <div>
              {preview.summary}
              {preview.system ? ` · ${preview.system}` : ""}
            </div>

            {/* The two facts worth reading before agreeing. */}
            <div>
              <div>
                <b>Installs:</b>{" "}
                {preview.installs || "nothing — you supply the emulator yourself"}
              </div>
              <div>
                <b>May write to:</b> {(preview.writes ?? []).join(", ") || "nothing"}
              </div>
            </div>

            {/* Deliberately blunt, and deliberately not softened by the checks
                that already ran. Those bound what a definition can reach; they
                cannot tell you whether its author meant well, and this file did
                not come from the plugin. */}
            <div className={DANGER_CLASS}>
              <b>You are responsible for what you import.</b> This definition was
              written by whoever gave it to you, not by this plugin, and nobody here
              has reviewed or tested it. It can make your Deck download and run
              software.{" "}
              <b>Open the .json in a text editor and read it before continuing</b> — it
              is a few lines, and every line is plain text.
            </div>

            {preview.replaces && (
              <div style={MUTED}>
                A definition for {preview.id} is already imported and will be
                overwritten.
              </div>
            )}
          </div>
        }
      />,
    );
  })();
}
