import { Field, ModalRoot } from "@decky/ui";

import type { ReceivedFile } from "./backend";
import { FileName } from "./FileName";
import { ownedNoun } from "./receivedGroups";
import { ScrollList, ScrollRow } from "./ScrollList";
import { humanSize } from "./TransferModal";

/**
 * What a playlist in the Received list is holding.
 *
 * The transfer dialog shows a CD rip as one row, because thirteen rows of one
 * game each offering **Add** is how a `.bin` came to be offered the add flow at
 * all. Folding them away raises the obvious question — *did the rest arrive?* —
 * and this is the answer, so the count in the row is checkable rather than
 * something the reader has to trust.
 *
 * Shaped like `OptionalFilesModal`, and for its reason: a line that counts, a
 * dialog that names, and a scroller whose rows can take focus, because one
 * whose rows cannot does not move under the sticks.
 */
interface Props {
  /** The sheet or playlist these belong to. */
  playlist: string;
  tracks: ReceivedFile[];
  closeModal?: () => void;
}

export function DiscTracksModal({ playlist, tracks, closeModal }: Props) {
  const noun = ownedNoun(playlist);

  return (
    <ModalRoot closeModal={closeModal} bAllowFullSize>
      {/*
       * The title says what this is; the name is below it. A rip arrives named
       * `Sunset Circuit (USA) (Track 01).bin` and a sheet can be longer still,
       * so a title built from one has no break to wrap at and runs out of the
       * dialog -- the same conclusion the delete confirmation reached.
       */}
      <h1 style={{ marginTop: 0, marginBottom: "4px", fontSize: "23px" }}>
        {noun === "track" ? "Tracks on this disc" : "Files in this set"}
      </h1>
      <div style={{ opacity: 0.7, fontSize: "13px", marginBottom: "12px" }}>
        <FileName name={playlist} mode="wrap" style={{ fontWeight: 600 }} />
        <div style={{ marginTop: "4px" }}>
          {noun === "track"
            ? "Raw sectors, which is why the sheet above is the one to add — it says where each track starts and the tracks themselves do not."
            : "The discs of one game and their tracks. Adding the playlist above adds all of it, in order."}{" "}
          Added and deleted together.
        </div>
      </div>
      {/* Four rows before it scrolls, as the optional files list settled on:
          a row is 64px over CEF on the device. */}
      <ScrollList style={{ maxHeight: "256px" }}>
        {tracks.map((track) => (
          <ScrollRow key={track.path}>
            <Field
              label={<FileName name={track.name} />}
              description={humanSize(track.size)}
            />
          </ScrollRow>
        ))}
      </ScrollList>
    </ModalRoot>
  );
}
