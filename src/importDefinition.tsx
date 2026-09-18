import { ConfirmModal } from "@decky/ui";
import { toaster } from "@decky/api";

import {
  importEmulatorDefinition,
  previewEmulatorDefinition,
  type DefinitionPreview,
} from "./backend";
import { DANGER_TEXT } from "./danger";
import { COLUMN, MUTED } from "./dialogStyle";
import { openModal } from "./modalStack";
import { ScrollList, ScrollRow } from "./ScrollList";

/**
 * One definition, as the confirmation describes it.
 *
 * A row in a list of nine keeps only what has to be agreed to: the name, that
 * it replaces something, and the two facts this dialog exists for -- what gets
 * downloaded and where it may write. The system, the summary and what you have
 * to supply are context rather than consent, and nine copies of them is what
 * pushed the warning off the bottom of the screen. They are all on the entry's
 * own row in the tab it lands in.
 *
 * A file holding one definition shows them: there is nothing to scroll and
 * nothing to crowd out.
 */
function rowFor(entry: DefinitionPreview, alone: boolean) {
  return (
    <div>
      <div>
        <b>{entry.name}</b>
        {alone && entry.system ? ` · ${entry.system}` : ""}
        {entry.replaces ? " (already imported)" : ""}
      </div>
      {alone && entry.summary && <div>{entry.summary}</div>}
      {/* The two facts worth reading before agreeing. */}
      <div style={MUTED}>
        Installs: {entry.installs || "nothing — you supply it yourself"} · May write
        to: {entry.writes.join(", ") || "nothing"}
      </div>
      {alone && entry.needs && <div style={MUTED}>You supply: {entry.needs}</div>}
    </div>
  );
}

/**
 * The entry list, bounded so the dialog itself never scrolls.
 *
 * A file may hold a dozen definitions, and with the whole body scrolling the
 * warning below the list is what goes off the bottom -- which is the one part
 * that must be read before agreeing. So the list scrolls inside this and
 * everything after it stays put.
 *
 * `38vh` rather than a pixel height: rows here are one to three lines, unlike
 * the fixed-height rows in `OptionalFilesModal`, whose comment records what
 * happens when the cap is too generous -- the list outgrows the dialog frame
 * and both scroll.
 */
const LIST = {
  display: "flex",
  flexDirection: "column" as const,
  gap: "8px",
  // Set here rather than per row, so it cascades to the name line and leaves
  // the muted line on its own 13px. A name is not a heading here -- the row is
  // a record of what is about to happen, and at body size nine of them is most
  // of the screen.
  fontSize: "14px",
  // About three rows. A row is a 14px name line, a 13px muted line that wraps
  // to two when the paths are long, and the 8px gap -- so this shows three and
  // usually clips a fourth, which is its own signal that there is more below.
  // A height rather than a fraction of the screen: the dialog has a fixed
  // amount of room left after the warning and the buttons, and `38vh` of rows
  // was most of it.
  maxHeight: "150px",
};

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
            {/* One entry is left as plain text: there is nothing to scroll, and
                a focusable row would take the focus the OK button has today. */}
            {only ? (
              rowFor(only, true)
            ) : (
              <ScrollList style={LIST}>
                {entries.map((entry) => (
                  <ScrollRow key={entry.id}>{rowFor(entry, false)}</ScrollRow>
                ))}
              </ScrollList>
            )}

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
              <b>You are responsible for what you import.</b> Nobody here wrote or
              reviewed this file, and it can make your Deck download and run
              software. <b>Read the .json before continuing.</b>
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
