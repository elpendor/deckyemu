import { useEffect, useState } from "react";

import { updateDotVisible, watchUpdates } from "./updateSignal";
import { updates } from "./host";

/**
 * The orange dot on DeckyEmu's Quick Access tab, while an update waits.
 *
 * The one surface that reaches somebody without them opening anything and
 * without interrupting what they are doing: the tab bar is on screen every
 * time the Quick Access menu is.
 *
 * Each build says where it sits (`updates.dotOffset`): the icon is in the tab
 * bar in one and beside the name in a list in the other. `position: absolute`
 * with no positioned wrapper of ours, so it resolves against the element the
 * icon is drawn in rather than the glyph.
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
        top: updates.dotOffset,
        right: updates.dotOffset,
        height: "10px",
        width: "10px",
        background: "orange",
        borderRadius: "50%",
      }}
    />
  );
}
