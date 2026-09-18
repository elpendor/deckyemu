import { Field, ModalRoot } from "@decky/ui";

import type { OptionalFile } from "./backend";
import { ScrollList, ScrollRow } from "./ScrollList";

/**
 * Every optional file the cores in use could read, and which cores those are.
 *
 * The line in the panel only counts them -- six cores in use declared 27 on
 * one Deck, far more than a subtitle holds. This is where they are named, for
 * anyone deciding whether a file they have is worth sending.
 *
 * Shaped like the restore dialog's emulator list, and for its reason: a list
 * this long needs a scroller, and a scroller only moves under the sticks when
 * its rows can take focus -- which a plain `Field` cannot, so each row carries
 * an `onActivate` that does nothing.
 */
interface Props {
  emulatorName: string;
  files: OptionalFile[];
  closeModal?: () => void;
}

export function OptionalFilesModal({ emulatorName, files, closeModal }: Props) {
  return (
    <ModalRoot closeModal={closeModal} bAllowFullSize>
      <h1 style={{ marginTop: 0, marginBottom: "4px", fontSize: "23px" }}>
        Optional files for {emulatorName}
      </h1>
      <div style={{ opacity: 0.7, fontSize: "13px", marginBottom: "12px" }}>
        Your games run without any of these. Send one and it is recognised by
        name, then installed where the core reads it.
      </div>
      {/* Four rows. A row is 64px measured over CEF on the device; at 55vh the
          list was 294px and pushed the dialog 28px past its own frame, so the
          whole dialog scrolled as well as the list. */}
      <ScrollList style={{ maxHeight: "256px" }}>
        {files.map((file) => (
          <ScrollRow key={file.name}>
            <Field
              label={file.name}
              description={[file.label, file.cores.length ? `Read by ${file.cores.join(", ")}` : ""]
                .filter(Boolean)
                .join(". ")}
            />
          </ScrollRow>
        ))}
      </ScrollList>
    </ModalRoot>
  );
}
