import { useEffect, useState } from "react";

import { updateDotVisible, watchUpdates } from "./updateSignal";

/**
 * The orange dot on the DeckyEmu icon in the Quick Access tab bar.
 *
 * The one surface that reaches somebody without them opening anything and
 * without interrupting what they are doing. It is also not an invention: decky
 * loader draws exactly this dot, in exactly this place, on its own plug icon
 * when a plugin update is waiting -- see its `NotificationBadge`. The geometry
 * below is copied from it deliberately, because a dot in a different spot or a
 * different colour is a new thing for the user to learn rather than one they
 * already read.
 *
 * `position: absolute` with no positioned wrapper of ours, again as decky does
 * it: the icon is handed to Steam's tab bar, and it is Steam's own element that
 * this resolves against. Wrapping it in a relative container of our own moves
 * the dot onto the glyph instead of the corner of the tab.
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
        top: "8px",
        right: "8px",
        height: "10px",
        width: "10px",
        background: "orange",
        borderRadius: "50%",
      }}
    />
  );
}
