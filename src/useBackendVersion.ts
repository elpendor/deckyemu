import { useCallback, useEffect, useState } from "react";

import { pluginVersion, type PluginVersion } from "./backend";
import { callWithRetry } from "./timeout";
import { logError } from "./logError";

/** How often to re-read which build is on disk while a panel is open. */
export const VERSION_POLL_MS = 4000;

/**
 * Which build of the plugin is on disk, kept current while a panel is open.
 *
 * Decky owns installing an update and the plugin reload that follows, and tells
 * this side nothing about either — so a version read once at mount went stale
 * the moment an update landed, and the panel went on showing the build it had
 * under a line still offering the update you had just installed. Leaving the
 * panel and coming back fixed it, which is the tell: a remount was the only
 * thing that ever re-read.
 *
 * Waiting on the install was the obvious fix and the wrong one. It assumed the
 * component that *started* the install is the one still on screen when it
 * lands, and a plugin reload is precisely what breaks that — the waiting
 * component is torn down, a new one mounts, reads a backend that has not
 * swapped yet, and never asks again. Polling from the panel survives it,
 * because whichever instance is alive does the asking.
 *
 * Cheap enough not to think about: one backend call answered in single-digit
 * milliseconds, every few seconds, only while somebody is looking at a panel
 * that shows a version.
 *
 * A hook rather than state in each panel, because two panels need it and the
 * one thing worse than polling twice is two copies of when to stop.
 */
export function useBackendVersion(): PluginVersion | null {
  const [version, setVersion] = useState<PluginVersion | null>(null);

  const read = useCallback(async () => {
    try {
      setVersion(await callWithRetry(pluginVersion));
    } catch (error) {
      logError("could not read version", error);
    }
  }, []);

  useEffect(() => {
    void read();
    const timer = setInterval(() => { void read(); }, VERSION_POLL_MS);
    return () => clearInterval(timer);
  }, [read]);

  return version;
}
