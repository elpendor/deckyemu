/**
 * A `window` for code that runs inside Steam.
 *
 * steam.ts reaches for `window.collectionStore`, `window.SteamClient` and
 * `window.appStore` -- undocumented globals the client injects. Under Node
 * there is no `window` at all, so those reads throw a ReferenceError before any
 * logic runs, and every test fails for a reason that has nothing to do with
 * what it was checking.
 *
 * Pointing `window` at `globalThis` means a test sets `globalThis.appStore` and
 * the code under test sees `window.appStore`, with no DOM library involved.
 */
if (typeof (globalThis as { window?: unknown }).window === "undefined") {
  (globalThis as { window?: unknown }).window = globalThis;
}
