/**
 * The bundle the service evaluates in Steam's UI, once the preload has put our
 * Quick Access tab in place.
 *
 * It connects the channel to the service, starts the panel, and fills the
 * preload's three placeholders: the tab, the `/deckyemu` page and the game menu
 * builder. A newer bundle evaluated over this one first calls `unload` here, so
 * nothing is registered twice.
 *
 * Whatever fails, the tab says so: a blank tab is the one outcome that tells
 * nobody anything.
 */

import type { Bridge } from "./preload/bridge";
import { call, connect } from "./host/channel";
import { resolveAll, steamLookups } from "./steamui";
import { start } from "./index";

declare const __DECKYEMU_VERSION__: string;

const bridge = (window as unknown as { __deckyemu?: Bridge }).__deckyemu;

if (!bridge?.qam) {
  console.error("[deckyemu] the preload is not in place; nothing to attach to");
} else {
  try {
    bridge.unload?.();
  } catch (error) {
    console.error("[deckyemu] the previous bundle did not unload cleanly", error);
  }
  try {
    connect();
    const started = start();
    bridge.qam.set({ icon: started.icon, title: started.title, content: started.content });
    bridge.pages.set(started.page);
    bridge.status.failed = undefined;
    bridge.status.started = __DECKYEMU_VERSION__;
    bridge.unload = () => {
      started.stop();
      bridge.unload = undefined;
    };
  } catch (error) {
    bridge.status.failed = error instanceof Error ? error.message : String(error);
    console.error("[deckyemu] could not start", error);
  }
  // What was and was not found in Steam, for the log and the diagnostic report.
  setTimeout(() => {
    resolveAll();
    void call("host.report_frontend", {
      version: __DECKYEMU_VERSION__,
      patches: bridge.status.patches,
      rendered: bridge.status.rendered,
      failed: bridge.status.failed ?? null,
      lookups: steamLookups(),
    }).catch(() => undefined);
  }, 15000);
}
