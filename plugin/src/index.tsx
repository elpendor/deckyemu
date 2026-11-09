/**
 * The plugin build's entry: the shared panel, registered with the loader.
 *
 * Everything the panel does is `start` in src/index.tsx, the same in both
 * builds. What is here is what the loader asks for and the service does not:
 * the plugin definition, the settings page's route, and its own title row.
 */

import { DialogButton, findModuleByExport, getReactRoot, quickAccessMenuClasses } from "./steamui";
import { definePlugin, routerHook } from "./host";
import { FaCog } from "react-icons/fa";

import { start } from "../../src/index";
import { MANAGE_ROUTE, openManagePage } from "../../src/ManagePage";
import { HEADER_BUTTON, SwitchButton } from "../../src/SwitchPanel";
import { keepDeckyRoutesWorking, type DeckyRouterHook } from "./repairRoutes";

/**
 * The plugin's row in the Quick Access header: its name, the switch to the
 * standalone version, and a way to the settings page.
 *
 * quickAccessMenuClasses.Title, not staticClasses.Title: the generic title
 * class carries its own padding and line height, which sat the name off-centre
 * against the loader's back arrow. 28x40 is what a Quick Access header button
 * measures across the plugins that put one there, and `marginRight: auto` on
 * the name pushes the button to the right edge. The glyph is centred by making
 * the button a flex container, not by nudging it.
 */
function TitleView() {
  return (
    <div
      className={quickAccessMenuClasses.Title}
      style={{ display: "flex", alignItems: "center", padding: 0, flex: "auto", boxShadow: "none" }}
    >
      <div style={{ marginRight: "auto" }}>DeckyEmu</div>
      <div style={{ display: "flex", gap: "6px", marginLeft: "5px" }}>
        <SwitchButton />
        <DialogButton style={HEADER_BUTTON} onClick={() => openManagePage()}>
          <FaCog style={{ display: "block" }} />
        </DialogButton>
      </div>
    </div>
  );
}

export default definePlugin(() => {
  const started = start();

  // Not exact: each tab has its own URL under this one (see `tabRoute`), and an
  // exact route leaves those unresolved, so tapping a tab navigates to nothing.
  // `started.page` is one component for the life of the module: the router
  // keeps what it is handed, and a new function each time would remount it.
  routerHook.addRoute(MANAGE_ROUTE, started.page);

  // After the route is added, so the router it remounts lists it. A no-op on
  // any Steam client the loader hooks by itself -- see repairRoutes.ts.
  void keepDeckyRoutesWorking({
    routerHook: () =>
      (window as unknown as { DeckyPluginLoader?: { routerHook?: DeckyRouterHook } })
        .DeckyPluginLoader?.routerHook,
    findModuleByExport,
    reactRoot: () => {
      const element = document.getElementById("root");
      return element ? getReactRoot(element) : null;
    },
  });

  return {
    name: "DeckyEmu",
    titleView: <TitleView />,
    content: started.content,
    icon: started.icon,
    onDismount() {
      routerHook.removeRoute(MANAGE_ROUTE);
      started.stop();
    },
  };
});
