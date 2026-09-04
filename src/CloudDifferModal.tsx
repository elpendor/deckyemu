import { ConfirmModal } from "@decky/ui";
import { toaster } from "@decky/api";

import { cloudTakeTheirs } from "./backend";
import { FileName } from "./FileName";
import { logError } from "./logError";
import { openModal } from "./modalStack";

/**
 * The one question the cloud half asks before a game starts.
 *
 * Everything else about a launch is decided without anybody: a save on the
 * storage that is not on this Deck comes down silently, because writing a file
 * that is not there cannot lose one. This is the other case -- the same file
 * exists in both places and they are not the same file -- and it is not a
 * decision to make on somebody's behalf.
 *
 * **It cannot be settled by looking at the dates.** Which copy is "newer"
 * depends on this Deck's clock, a storage provider's clock, and whatever
 * device wrote the other one, none of which have been compared. Ludusavi
 * refuses the same guess for the same reason and warns instead; both decky
 * plugins keep the loser of a conflict rather than deleting it. So this asks,
 * and the answer stands on what a person knows about their own week rather
 * than on arithmetic.
 *
 * **The launch is already going by the time this shows.** The launcher waits on
 * a file for a bounded few seconds, and that wait is over before the question
 * is answered -- so this cannot hold a game open indefinitely for an answer
 * nobody is there to give. Taking the storage's copy therefore says to start
 * the game again, because the emulator has already read what was on disk.
 */
export function showCloudDiffer(options: {
  appId: number;
  coreId: string;
  title: string;
  names: string[];
}): void {
  const { appId, coreId, title, names } = options;
  openModal(
    <ConfirmModal
      strTitle="Your cloud saves are different"
      strOKButtonText="Use the cloud copy"
      strCancelButtonText="Keep this Deck's"
      onOK={() => {
        void (async () => {
          try {
            const result = await cloudTakeTheirs(appId, coreId, names);
            if (!result.ok) {
              toaster.toast({
                title: "Could not bring those down",
                body: result.error ?? "The storage did not answer.",
              });
              return;
            }
            // Said plainly, because the emulator read the old files as it
            // started and nothing here can make it read them again.
            toaster.toast({
              title: "Cloud saves are in place",
              body: `Start ${title} again to play from them.`,
            });
          } catch (error) {
            logError("could not take the cloud's copy of a save", error);
            toaster.toast({ title: "Could not bring those down", body: "Something went wrong." });
          }
        })();
      }}
      strDescription={
        <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
          <div>
            {names.length === 1
              ? `One save for ${title} is different in your cloud storage than on this Deck.`
              : `${names.length} saves for ${title} are different in your cloud storage than on this Deck.`}{" "}
            This usually means it was played somewhere else since this Deck last
            copied anything up.
          </div>
          {/* Named, because "a save is different" is not something anybody can
              act on. Three at most: this is a dialog over a game that is
              starting, not a report. */}
          <div style={{ fontSize: "13px", opacity: 0.8 }}>
            {names.slice(0, 3).map((name) => (
              <FileName key={name} name={name} />
            ))}
            {names.length > 3 && <div>and {names.length - 3} more</div>}
          </div>
          <div style={{ fontSize: "13px", opacity: 0.8 }}>
            Keeping this Deck's changes nothing now, and the next copy up will put
            them in your storage — the versions being replaced are kept there, so
            neither answer here loses anything.
          </div>
        </div>
      }
    />,
  );
}
