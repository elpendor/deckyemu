import { useEffect, useState } from "react";

import { updateDotVisible, watchUpdates } from "./updateSignal";

/**
 * The orange dot on DeckyEmu's row in decky's plugin list.
 *
 * The one surface that reaches somebody without them opening anything and
 * without interrupting what they are doing. It is also not an invention: it is
 * decky's own `NotificationBadge`, which decky puts on a store plugin's row when
 * an update is waiting -- HLTB's, say -- and a dot in a different spot is a new
 * thing for the user to learn rather than one they already read.
 *
 * **The offsets are the list's, not the tab bar's.** Decky draws the badge in
 * two places: 8px inside the corner of its plug icon in the Quick Access tab
 * bar, and -5px, just outside the corner of the button, on a row in the plugin
 * list (`PluginView` passes that override). Our icon is only ever rendered in
 * the list, beside the name, so the tab bar's numbers put the dot inside the
 * button next to the text while HLTB's sat on the corner above it.
 *
 * `position: absolute` with no positioned wrapper of ours, again as decky does
 * it: it resolves against the row's button, the same element decky's badge
 * does. Wrapping it in a relative container of our own moves the dot onto the
 * glyph instead.
 */
function useUpdateDot(): boolean {
  const [show, setShow] = useState<boolean>(updateDotVisible);

  useEffect(() => {
    // Read again before subscribing. The backend's first check, and the read of
    // the stored setting, can both land between this rendering and the effect
    // running -- and a dot that is only ever set by an event nobody was
    // listening for yet would stay dark until the next check hours later.
    setShow(updateDotVisible());
    return watchUpdates(() => setShow(updateDotVisible()));
  }, []);

  return show;
}

export function UpdateDot() {
  if (!useUpdateDot()) return null;

  return (
    <div
      style={{
        position: "absolute",
        top: "-5px",
        right: "-5px",
        height: "10px",
        width: "10px",
        background: "orange",
        borderRadius: "50%",
      }}
    />
  );
}
