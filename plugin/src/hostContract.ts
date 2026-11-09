/**
 * The plugin build swaps four modules for its own (see SWAPS in
 * rollup.config.js). Shared code is type-checked against the service's side
 * only, so this holds each plugin module to the names the service's exports:
 * a name missing here fails the type check, not a Deck at runtime.
 *
 * A name only the service has, and shared code never imports, goes in the
 * matching ServiceOnly list.
 */

import type * as ServiceHost from "../../src/host/index";
import type * as ServiceSteamUI from "../../src/steamui/index";
import type * as ServiceBase from "../../src/steamui/base";
import type * as ServiceMenu from "../../src/steam/contextMenu";
import type * as PluginHost from "./host";
import type * as PluginSteamUI from "./steamui";
import type * as PluginBase from "./steamuiBase";
import type * as PluginMenu from "./contextMenu";

/** The names `Service` exports that `Plugin` does not, less the allowed. */
type Missing<Service, Plugin, ServiceOnly extends PropertyKey = never> = Exclude<
  keyof Service,
  keyof Plugin | ServiceOnly
>;

/** Compiles only while `Names` is empty; otherwise the error lists them. */
type None<Names extends PropertyKey> = { [K in Names]: "missing from the plugin build" };

export const host: None<Missing<typeof ServiceHost, typeof PluginHost>> = {};
/** The service's own UI plumbing: its entry (src/main.tsx), the host layer
 * and src/ui use these, never the shared panel through steamui. */
type SteamUIServiceOnly =
  | "mainWindow"
  | "SideMenu"
  | "useCurrentPath"
  | "useQuickAccessVisible"
  | "steamLookups"
  | "resolveAll"
  | "registerLookup";

export const steamui: None<
  Missing<typeof ServiceSteamUI, typeof PluginSteamUI, SteamUIServiceOnly>
> = {};
export const base: None<Missing<typeof ServiceBase, typeof PluginBase>> = {};
export const menu: None<Missing<typeof ServiceMenu, typeof PluginMenu>> = {};
