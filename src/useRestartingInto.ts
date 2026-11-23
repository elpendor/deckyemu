import { useEffect, useState } from "react";

import { restartingInto, watchUpdates } from "./updateSignal";

/** The version DeckyEmu is restarting into right now, or empty. */
export function useRestartingInto(): string {
  const [version, setVersion] = useState<string>(restartingInto);
  useEffect(() => {
    setVersion(restartingInto());
    return watchUpdates(() => setVersion(restartingInto()));
  }, []);
  return version;
}
