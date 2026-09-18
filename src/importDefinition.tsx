import { ConfirmModal } from "@decky/ui";
import { toaster } from "@decky/api";

import { importEmulatorDefinition, previewEmulatorDefinition } from "./backend";
import { DANGER_TEXT } from "./danger";
import { COLUMN, MUTED } from "./dialogStyle";
import { openModal } from "./modalStack";

/**
 * Importing definitions: read the file, show what each will do, store them.
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
 *
 * One file may hold one definition or a dozen, and emulators and ports sit in
 * the same file, so this handles a list of any length rather than having a
 * second dialog for the second shape.
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
    const entries = preview.entries ?? [];
    const problems = preview.problems ?? [];
    const replacing = entries.some((entry) => entry.replaces);
    const only = entries.length === 1 ? entries[0] : null;

    const go = () =>
      void (async () => {
        const result = await importEmulatorDefinition(name, replacing);
        if (!result.ok) {
          toaster.toast({ title: "Could not import", body: result.error ?? "" });
          return;
        }
        const count = result.imported?.length ?? 0;
        toaster.toast({
          title: only
            ? `${only.name} imported`
            : `${count} definition${count === 1 ? "" : "s"} imported`,
          body: only && !only.installs
            ? "Find it under Emulators and point it at the binary."
            : "Find them under Emulators and Ports, and press install.",
        });
        onImported?.();
      })();

    openModal(
      <ConfirmModal
        strTitle={
          only
            ? `${only.replaces ? "Replace" : "Import"} ${only.name}?`
            : `Import ${entries.length} definitions?`
        }
        strOKButtonText={replacing ? "Replace" : "Import"}
        onOK={go}
        strDescription={
          <div style={{ ...COLUMN, gap: "10px" }}>
            {entries.map((entry) => (
              <div key={entry.id}>
                <div>
                  <b>{entry.name}</b>
                  {entry.system ? ` · ${entry.system}` : ""}
                  {entry.replaces ? " (replaces the one already imported)" : ""}
                </div>
                {only && entry.summary && <div>{entry.summary}</div>}
                {/* The two facts worth reading before agreeing. */}
                <div style={MUTED}>
                  Installs: {entry.installs || "nothing — you supply it yourself"} ·
                  May write to: {entry.writes.join(", ") || "nothing"}
                </div>
                {entry.needs && <div style={MUTED}>You supply: {entry.needs}</div>}
              </div>
            ))}

            {problems.length > 0 && (
              <div style={MUTED}>
                Not imported: {problems.map((problem) => problem.split("\n")[0]).join("; ")}
              </div>
            )}

            {/* Deliberately blunt, and deliberately not softened by the checks
                that already ran. Those bound what a definition can reach; they
                cannot tell you whether its author meant well, and this file did
                not come from the plugin. */}
            <div style={DANGER_TEXT}>
              <b>You are responsible for what you import.</b> This file was written by
              whoever gave it to you, not by this plugin, and nobody here has reviewed
              or tested it. It can make your Deck download and run software.{" "}
              <b>Open the .json in a text editor and read it before continuing.</b>
            </div>

            {/* Said here because this is where it lands, the same rule firmware
                follows for the same reason: the transfer folder is a staging
                post, so importing takes the file out of it. Somebody who wants
                to keep the .json has one on the device they sent it from. */}
            <div style={MUTED}>
              {problems.length
                ? "The file stays in the transfer folder, because some entries were not imported."
                : "The file is moved out of the transfer folder once it is imported."}
            </div>
          </div>
        }
      />,
    );
  })();
}
