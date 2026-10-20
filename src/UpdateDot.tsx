import { useEffect, useState } from "react";

import { updateDotVisible, watchUpdates } from "./updateSignal";

/**
 * The orange dot on DeckyEmu's Quick Access tab, while an update waits.
 *
 * The one surface that reaches somebody without them opening anything and
 * without interrupting what they are doing: the tab bar is on screen every
 * time the Quick Access menu is.
 *
 * 8px inside the corner of the tab, the offset an icon badge in that bar
 * takes. `position: absolute` with no positioned wrapper of ours, so it
 * resolves against Steam's tab element rather than the glyph.
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
