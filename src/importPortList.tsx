import { ConfirmModal } from "@decky/ui";
import { toaster } from "@decky/api";

import { importPortListFile, previewPortList } from "./backend";
import { DANGER_TEXT } from "./danger";
import { COLUMN, MUTED } from "./dialogStyle";
import { openModal } from "./modalStack";

/**
 * Importing a ports list: read it, show what each port installs, then
 * store them.
 *
 * The same two entrances and the same warning as an emulator definition -- see
 * `importDefinition` -- because a port is one: something this file makes the
 * Deck download and run.
 */
export function importPortList(name: string, onImported?: () => void): void {
  void (async () => {
    const preview = await previewPortList(name);
    if (!preview.ok) {
      toaster.toast({ title: "Could not import", body: preview.error ?? "" });
      return;
    }
    const ports = preview.ports ?? [];
    const problems = preview.problems ?? [];

    const go = () =>
      void (async () => {
        const result = await importPortListFile(name);
        if (!result.ok) {
          toaster.toast({ title: "Could not import", body: result.error ?? "" });
          return;
        }
        const count = result.imported?.length ?? 0;
        toaster.toast({
          title: `${count} port${count === 1 ? "" : "s"} imported`,
          body: "Find them under Ports and press install.",
        });
        onImported?.();
      })();

    openModal(
      <ConfirmModal
        strTitle={`Import ${ports.length} port${ports.length === 1 ? "" : "s"}?`}
        strOKButtonText="Import"
        onOK={go}
        strDescription={
          <div style={{ ...COLUMN, gap: "10px" }}>
            {ports.map((port) => (
              <div key={port.id}>
                <div>
                  <b>{port.name}</b>
                  {port.replaces ? " (replaces the one already imported)" : ""}
                </div>
                <div style={MUTED}>
                  Installs: {port.installs || "nothing"} · May write to:{" "}
                  {port.writes.join(", ") || "nothing"}
                </div>
                {port.needs && <div style={MUTED}>You supply: {port.needs}</div>}
              </div>
            ))}

            {problems.length > 0 && (
              <div style={MUTED}>
                Not imported: {problems.map((problem) => problem.split("\n")[0]).join("; ")}
              </div>
            )}

            <div style={DANGER_TEXT}>
              <b>You are responsible for what you import.</b> This list was written by
              whoever gave it to you, not by this plugin, and nobody here has reviewed
              or tested it. It can make your Deck download and run software.{" "}
              <b>Open the .json in a text editor and read it before continuing.</b>
            </div>

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
