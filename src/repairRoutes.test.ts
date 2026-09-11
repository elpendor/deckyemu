import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./logError", () => ({ logError: () => undefined }));

const { isRouteComponent, keepDeckyRoutesWorking, repairDeckyRoutes } = await import("./repairRoutes");

/*
 * Steam's `Route`, as each client minifies it. Built from strings because the
 * matcher reads the function's source, and a literal written here would be
 * reformatted by the compiler before the test ever saw it.
 */
const betaRoute = new Function("q", "return {routePath:ve.match?.path,disabled:!ve.match}");
const stableRoute = new Function("q", "return {routePath:e.match?.path,disabled:!e.match}");
const olderRoute = new Function("q", "return {routePath:null===(t=e.match)?void 0:t.path}");

class Boundary {
  renders: unknown[] = [];
  callsBack = true;
  render(): unknown {
    return "children";
  }
  forceUpdate(callback?: () => void) {
    this.renders.push(this.render());
    if (this.callsBack) callback?.();
  }
}

/** A root, Steam's error boundary, decky's patched router, and what it rendered. */
function world({ route, wrapped, patched = true }: { route?: unknown; wrapped: boolean; patched?: boolean }) {
  const wrapper = function DeckyGamepadRouterWrapper() {};
  const patchObject = { type: () => null };
  const instance = new Boundary();
  const root: any = { tag: 3 };
  const boundary: any = { tag: 1, stateNode: instance, return: root };
  const router: any = { tag: 15, elementType: patchObject, return: boundary };
  const rendered: any = { tag: 0, type: wrapped ? wrapper : function SteamSwitch() {}, return: router };
  root.child = boundary;
  boundary.child = router;
  router.child = rendered;

  const hook: any = {
    Route: route,
    DeckyGamepadRouterWrapper: wrapper,
    gamepadRouterPatch: patched ? { object: patchObject } : undefined,
  };
  const findModuleByExport = vi.fn((filter: (value: unknown) => boolean): unknown =>
    filter("router-backstack") ? { a: "router-backstack", b: () => 1, c: betaRoute } : undefined,
  );
  const env = { routerHook: () => hook, findModuleByExport, reactRoot: () => root };
  return { hook, env, instance, findModuleByExport };
}

describe("recognising Steam's Route component", () => {
  it("matches the beta client, whose minifier uses longer names", () => {
    expect(isRouteComponent(betaRoute)).toBe(true);
  });

  it("still matches the shapes decky already knows", () => {
    expect(isRouteComponent(stableRoute)).toBe(true);
    expect(isRouteComponent(olderRoute)).toBe(true);
  });

  it("matches nothing else", () => {
    expect(isRouteComponent(() => 1)).toBe(false);
    expect(isRouteComponent("routePath:ve.match?.path,")).toBe(false);
  });
});

describe("repairing decky's pages", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("leaves a client decky hooked alone", () => {
    const { env, instance, findModuleByExport } = world({ route: stableRoute, wrapped: true });

    expect(repairDeckyRoutes(env)).toBe("healthy");
    expect(instance.renders).toEqual([]);
    expect(findModuleByExport).not.toHaveBeenCalled();
  });

  it("fills in the Route decky could not find and remounts the router", () => {
    const { env, hook, instance } = world({ wrapped: false });

    expect(repairDeckyRoutes(env)).toBe("repaired");
    expect(hook.Route).toBe(betaRoute);
    // Nothing for one pass, which unmounts the router, then the real render.
    expect(instance.renders).toEqual([null, "children"]);
    expect(Object.prototype.hasOwnProperty.call(instance, "render")).toBe(false);
  });

  it("remounts when decky's routes were built before the Route was there", () => {
    const { env, instance } = world({ wrapped: true });

    expect(repairDeckyRoutes(env)).toBe("repaired");
    expect(instance.renders).toEqual([null, "children"]);
  });

  it("remounts a router that never rendered through decky, even with a Route", () => {
    const { env, instance } = world({ route: stableRoute, wrapped: false });

    expect(repairDeckyRoutes(env)).toBe("repaired");
    expect(instance.renders).toEqual([null, "children"]);
  });

  it("touches nothing when there is no Route to be found", () => {
    const { env, hook, instance } = world({ wrapped: false });
    env.findModuleByExport.mockReturnValue({ a: "router-backstack", b: () => 1 });

    expect(repairDeckyRoutes(env)).toBe("unrepairable");
    expect(hook.Route).toBeUndefined();
    expect(instance.renders).toEqual([]);
  });

  it("puts the boundary back even if React never calls back", () => {
    const { env, instance } = world({ wrapped: false });
    instance.callsBack = false;

    repairDeckyRoutes(env);
    expect(instance.renders).toEqual([null]);

    vi.advanceTimersByTime(1000);
    expect(instance.renders).toEqual([null, "children"]);
    expect(Object.prototype.hasOwnProperty.call(instance, "render")).toBe(false);
  });

  it("waits for decky to patch the router, then repairs it", async () => {
    const { env, hook, instance } = world({ wrapped: false, patched: false });
    const patchObject = { type: () => null };

    const outcome = keepDeckyRoutesWorking(env, 5, 2000);
    await vi.advanceTimersByTimeAsync(2000);
    expect(instance.renders).toEqual([]);

    hook.gamepadRouterPatch = { object: patchObject };
    (env.reactRoot() as any).child.child.elementType = patchObject;
    await vi.advanceTimersByTimeAsync(2000);

    expect(await outcome).toBe("repaired");
    expect(instance.renders).toEqual([null, "children"]);
  });
});
