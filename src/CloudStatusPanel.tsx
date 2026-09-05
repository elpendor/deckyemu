import { ButtonItem, Field, PanelSection, PanelSectionRow } from "@decky/ui";
import { addEventListener, removeEventListener, useQuickAccessVisible } from "@decky/api";
import { useCallback, useEffect, useState } from "react";

import { cloudBackupNow, cloudStatus, cloudWaiting } from "./backend";
import { logError } from "./logError";
import { ProgressBar } from "./TransferModal";
import { useCopyPercent } from "./useCopyPercent";
import { namesOf } from "./waitingNames";

/**
 * That saves are moving right now, for the panel you can actually reach.
 *
 * Two of the four copies start on their own -- closing a game copies that
 * emulator up, starting one brings down what is missing -- and both were
 * silent by design, on the grounds that a toast after every game is a
 * notification people turn off. The trouble with silent is that it is
 * indistinguishable from broken: the only sign was a date on the Library tab
 * of the Manage page, four navigations from here, and an after-play copy is
 * over in under twenty seconds. Measured on the device, twice, trying to get
 * there in time.
 *
 * So it says so here, where the plugin opens, and nowhere else costs anything:
 * like `TransferStatusPanel` this renders nothing at all when nothing is
 * moving, which is almost always.
 */
const SAYS: Record<string, string> = {
  // Named by what was happening, not by which copy it is: "after-play" is a
  // word from the backend, and the person reading just closed a game.
  "after-play": "The saves from the game you just closed are going up.",
  launch: "Bringing down saves this Deck does not have yet.",
  backup: "Copying your saves to your cloud storage.",
  restore: "Bringing saves back from your cloud storage.",
};

//: When the waiting list was last read, so opening the panel repeatedly does
//: not walk every save directory on the Deck each time. A copy finishing clears
//: it, because that is when the answer really changes.
let askedAt = 0;
const ASK_EVERY_MS = 60000;

export function CloudStatusPanel() {
  const [copying, setCopying] = useState("");
  const [overdue, setOverdue] = useState<{ id: string; name: string }[]>([]);
  const percent = useCopyPercent(copying);
  const visible = useQuickAccessVisible();

  const load = useCallback(async () => {
    try {
      // `false`: the local half of the status. Asking the provider who you are
      // is two round trips, and this row is on the path of every panel open.
      const status = await cloudStatus(false);
      setCopying(String(status.copying || ""));
      // Only worth asking when the automatic copy is meant to be happening:
      // with it switched off, saves piling up is the choice somebody made, not
      // a fault, and the Library tab is where that is dealt with.
      if (!status.remote || !status.after_play) {
        setOverdue([]);
      } else if (Date.now() - askedAt > ASK_EVERY_MS) {
        askedAt = Date.now();
        setOverdue((await cloudWaiting()).overdue || []);
      }
    } catch (error) {
      logError("could not read what the cloud is doing", error);
    }
  }, []);

  // Once per open, which catches a copy that began while the panel was closed
  // -- the usual case, since quitting a game is what starts most of them.
  useEffect(() => {
    if (visible) void load();
  }, [visible, load]);

  // And live after that, because the copy worth showing is the one that starts
  // while somebody is already looking. Said by the backend rather than polled:
  // there is no moment this end could know to ask.
  useEffect(() => {
    const moving = addEventListener<[kind: string]>("cloud_copying", (kind) => {
      setCopying(kind || "");
      // A copy that has just finished is exactly when the list changes, so the
      // next open asks rather than repeating what it knew before.
      if (!kind) askedAt = 0;
    });
    return () => removeEventListener("cloud_copying", moving);
  }, []);

  if (!copying) {
    if (!overdue.length) return null;
    // **Not a badge, and not while anything is moving.** Right after a game
    // closes every save is waiting, which is why the ordinary wait says
    // nothing anywhere near here. What is left is saves no copy is coming
    // back for -- a storage that stopped accepting them, or an emulator
    // nobody has opened since one failed -- which is the state that ends in
    // somebody losing a save while believing they were covered.
    return (
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            label="Saves not copied"
            description={`${namesOf(overdue)} ${
              overdue.length === 1 ? "has" : "have"
            } saves that have not reached your storage.`}
            onClick={() => {
              void cloudBackupNow(overdue.map((one) => one.id))
                .then(() => setOverdue([]))
                .catch((error) => logError("could not start the copy", error));
            }}
          >
            Copy them now
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    );
  }

  return (
    <PanelSection>
      <PanelSectionRow>
        <Field
          label="Copying saves"
          description={SAYS[copying] ?? "Your saves are being copied."}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={{ paddingBottom: "8px" }}>
          <ProgressBar fraction={percent < 0 ? -1 : percent / 100} />
        </div>
      </PanelSectionRow>
    </PanelSection>
  );
}
