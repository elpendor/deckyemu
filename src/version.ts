/**
 * What this bundle is, and whether it matches the backend it is talking to.
 *
 * The two halves of a decky plugin load independently: decky restarts the Python
 * backend whenever its files change, while the Steam client keeps whatever
 * frontend bundle it has already evaluated. After an update those can disagree for
 * as long as Steam stays running, and the symptom is that a change appears to have
 * done nothing at all -- indistinguishable from a bug in the change.
 *
 * So each half carries its own stamp and the panel compares them.
 */

// Both identifiers are declared in types.d.ts rather than here, and the reason
// is mechanical: rollup substitutes them in the source before parsing, and a
// `declare const __DECKYEMU_VERSION__` sitting in a real module would be
// rewritten into `declare const "0.5.0"`. Ambient declarations are not modules,
// so they never reach the transform.

export const FRONTEND_VERSION = __DECKYEMU_VERSION__;
export const FRONTEND_BUILD = __DECKYEMU_BUILD__;

/**
 * Whether this bundle was built from source rather than published.
 *
 * The gate on anything that must never reach a user. It is a constant folded in
 * at build time, so `IS_DEV_BUILD && <Thing/>` leaves no Thing in a release
 * bundle at all -- not hidden, absent. CI sets DECKYEMU_BUILD to the commit and
 * then greps dist/index.js to prove it took, so this cannot silently stay true.
 *
 * The backend gates the same features separately, on CI's build.json. Two gates
 * because this one only protects one artifact, and the Python half is reachable
 * by anything that can talk to the plugin.
 */
export const IS_DEV_BUILD = __DECKYEMU_BUILD__ === "dev";

/** Short form for display: "0.1.0 (a1b2c3d)", or just "0.1.0 (dev)". */
export function shortBuild(build: string): string {
  return build === "dev" ? "dev" : build.slice(0, 7);
}

export function describe(version: string, build: string): string {
  return `${version} (${shortBuild(build)})`;
}

/**
 * True when the running frontend is not the one that shipped with this backend.
 *
 * Compared on the build stamp rather than the version: a rebuild from the same
 * commit is the same code, and two builds of the same *version* from different
 * commits are not.
 */
export function isStale(backendVersion: string, backendBuild: string): boolean {
  // A local build has no meaningful stamp to compare, so never nag during
  // development -- the deploy loop replaces both halves anyway.
  if (backendBuild === "dev" || FRONTEND_BUILD === "dev") return false;
  return backendBuild !== FRONTEND_BUILD || backendVersion !== FRONTEND_VERSION;
}
