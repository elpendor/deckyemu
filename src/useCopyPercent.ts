import { addEventListener, removeEventListener } from "@decky/api";
import { useEffect, useState } from "react";

/**
 * How far along the copy named by `copying` is, or -1 when it has not said yet.
 *
 * Shared by the two places that draw a bar for it -- the Quick Access row and
 * the Library tab's own row -- because they are the same bar for the same copy,
 * and two copies of this were two chances for them to disagree.
 *
 * Below zero rather than zero until rclone's first stats line: `ProgressBar`
 * draws that as a sweep, which is what a copy that finishes in under a second
 * should look like, rather than a bar that sat empty and then vanished.
 *
 * Filtered by kind, because the copy after the last game and the fetch before
 * the next one can overlap, and a bar fed by both reads as one going backwards.
 */
export function useCopyPercent(copying: string) {
  const [percent, setPercent] = useState(-1);

  useEffect(() => {
    setPercent(-1);
    if (!copying) return;
    const progress = addEventListener<
      [name: string, done: number, phase: string, kind: string]
    >("cloud_sync_progress", (_name, done, _phase, kind) => {
      if (kind !== copying) return;
      setPercent(done);
    });
    return () => removeEventListener("cloud_sync_progress", progress);
  }, [copying]);

  return percent;
}
