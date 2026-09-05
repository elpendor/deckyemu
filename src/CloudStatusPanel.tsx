import { Field, PanelSection, PanelSectionRow } from "@decky/ui";
import { addEventListener, removeEventListener, useQuickAccessVisible } from "@decky/api";
import { useCallback, useEffect, useState } from "react";

import { cloudStatus } from "./backend";
import { logError } from "./logError";
import { ProgressBar } from "./TransferModal";
import { useCopyPercent } from "./useCopyPercent";

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

export function CloudStatusPanel() {
  const [copying, setCopying] = useState("");
  const percent = useCopyPercent(copying);
  const visible = useQuickAccessVisible();

  const load = useCallback(async () => {
    try {
      // `false`: the local half of the status. Asking the provider who you are
      // is two round trips, and this row is on the path of every panel open.
      setCopying(String((await cloudStatus(false)).copying || ""));
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
    const moving = addEventListener<[kind: string]>("cloud_copying", (kind) =>
      setCopying(kind || ""),
    );
    return () => removeEventListener("cloud_copying", moving);
  }, []);

  if (!copying) return null;

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
