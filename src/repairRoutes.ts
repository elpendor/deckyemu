import { logError } from "./logError";

/**
 * Keep decky's fullscreen pages working on a Steam client decky cannot fully
 * hook. This plugin's settings page is one of them.
 *
 * Decky puts a plugin's page into Steam's router in two steps: it finds Steam's
 * `Route` component by matching its minified source, then patches the router
 * and forces it to render again through Steam's error boundary. The September
 * 2026 beta client broke both. The matchers expect one-letter identifiers and
 * the minifier now emits longer ones, so decky logs "Failed to find Route
 * component", disables its error boundary hook, and every page it serves --
 * its own store and settings included -- is an empty screen with only the
 * footer drawn. The upstream fix is decky-loader#962.
 *
 * This does what that fix does, and only where decky has visibly failed: a
 * `Route` it could not find, or a patched router that never rendered through
 * decky's wrapper. On a client decky handles it touches nothing, so it retires
 * itself once the fix ships.
 */

/** The parts of a React fiber this walks. */
interface Fiber {
  tag?: number;
  type?: unknown;
  elementType?: unknown;
  stateNode?: unknown;
  child?: Fiber | null;
  sibling?: Fiber | null;
  return?: Fiber | null;
}

/** The fields of decky's RouterHook this reads and, for `Route`, writes. */
export interface DeckyRouterHook {
  Route?: unknown;
  DeckyGamepadRouterWrapper?: unknown;
  gamepadRouterPatch?: { object?: unknown };
}

interface ClassInstance {
  render?: () => unknown;
  forceUpdate: (callback?: () => void) => void;
}

export interface RouteRepairEnv {
  routerHook: () => DeckyRouterHook | undefined;
  findModuleByExport: (filter: (value: unknown) => boolean, minExports?: number) => unknown;
  reactRoot: () => Fiber | null | undefined;
}

export type RouteRepair = "healthy" | "repaired" | "waiting" | "unrepairable";

/** React's tag for a class component -- the only kind that can be told to render. */
const CLASS_COMPONENT = 1;

/** The whole of Steam's tree is a few thousand fibers; this is a runaway guard. */
const FIBER_LIMIT = 200_000;

/** How long a boundary may render nothing before it is put back regardless. */
const RESTORE_AFTER = 1000;

/** Decky's two matchers, with any identifier where decky's allow one letter. */
const ROUTE_SOURCE = [
  /routePath:[\w$]+\.match\?\.path./,
  /routePath:null===\([\w$]+=[\w$]+\.match\)/,
];

export function isRouteComponent(value: unknown): boolean {
  if (typeof value !== "function") return false;
  try {
    const source = Function.prototype.toString.call(value);
    return ROUTE_SOURCE.some((pattern) => pattern.test(source));
  } catch {
    return false;
  }
}

function findFiber(start: Fiber | null | undefined, match: (fiber: Fiber) => boolean): Fiber | null {
  const pending: Fiber[] = start ? [start] : [];
  for (let visited = 0; pending.length > 0 && visited < FIBER_LIMIT; visited++) {
    const fiber = pending.pop() as Fiber;
    if (match(fiber)) return fiber;
    if (fiber.sibling) pending.push(fiber.sibling);
    if (fiber.child) pending.push(fiber.child);
  }
  return null;
}

function isClassInstance(value: unknown): value is ClassInstance {
  return typeof (value as ClassInstance | null)?.forceUpdate === "function";
}

/**
 * Unmount everything under `instance` and mount it again -- what decky's own
 * `_deckyForceRerender` does. The router is memoised and takes no props, so it
 * never renders again by itself, and a patch applied after it mounted stays
 * unused until something remounts it.
 *
 * `render` is shadowed for exactly one pass. It has to come back even if React
 * never calls back, because a boundary left rendering nothing takes the whole
 * screen with it -- hence the timer behind the callback.
 */
function remount(instance: ClassInstance): void {
  const restore = () => {
    if (!Object.prototype.hasOwnProperty.call(instance, "render")) return;
    delete instance.render;
    instance.forceUpdate();
  };
  instance.render = () => null;
  try {
    instance.forceUpdate(restore);
  } catch (error) {
    restore();
    throw error;
  }
  setTimeout(restore, RESTORE_AFTER);
}

export function repairDeckyRoutes(env: RouteRepairEnv): RouteRepair {
  const hook = env.routerHook();
  // Without the wrapper to look for there is no telling a working router from
  // a broken one, and remounting a working one redraws the whole screen.
  if (!hook || typeof hook.DeckyGamepadRouterWrapper !== "function") return "unrepairable";

  let filled = false;
  if (!hook.Route) {
    const module = env.findModuleByExport((value) => value === "router-backstack", 20);
    const route =
      module && typeof module === "object" ? Object.values(module).find(isRouteComponent) : undefined;
    if (!route) return "unrepairable";
    hook.Route = route;
    filled = true;
  }

  const patched = hook.gamepadRouterPatch?.object;
  if (!patched) return "waiting";
  const router = findFiber(env.reactRoot(), (fiber) => fiber.elementType === patched);
  if (!router) return "waiting";

  // A wrapper that rendered while `Route` was missing built its route list out
  // of elements with no type, so filling it in needs the remount as well.
  const wrapped = findFiber(router.child, (fiber) => fiber.type === hook.DeckyGamepadRouterWrapper);
  if (wrapped && !filled) return "healthy";

  let boundary = router.return;
  while (boundary && !(boundary.tag === CLASS_COMPONENT && isClassInstance(boundary.stateNode))) {
    boundary = boundary.return;
  }
  if (!boundary) return "unrepairable";
  remount(boundary.stateNode as ClassInstance);
  return "repaired";
}

/**
 * Repair once decky has patched the router. Decky waits for the router to
 * exist before patching it, and a plugin can load before that has happened.
 */
export async function keepDeckyRoutesWorking(
  env: RouteRepairEnv,
  attempts = 15,
  every = 2000,
): Promise<RouteRepair> {
  for (let attempt = 1; ; attempt++) {
    let outcome: RouteRepair;
    try {
      outcome = repairDeckyRoutes(env);
    } catch (error) {
      logError("could not repair decky's pages", error);
      return "unrepairable";
    }
    if (outcome === "waiting" && attempt < attempts) {
      await new Promise((resolve) => setTimeout(resolve, every));
      continue;
    }
    // Both as errors, including the success: only console.error from plugin
    // code reaches Steam's cef_log.txt, which is where anyone diagnosing a
    // blank page will look. info, log and warn are dropped.
    if (outcome === "repaired") {
      console.error("[deckyemu] decky could not hook this Steam client's router; repaired it");
    } else if (outcome !== "healthy") {
      console.error(`[deckyemu] decky's pages may be blank on this Steam client (${outcome})`);
    }
    return outcome;
  }
}
