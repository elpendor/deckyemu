/**
 * Everything that talks to the Steam client.
 *
 * These are undocumented internal APIs, so each one is called defensively and
 * the shapes are declared locally rather than imported -- a Steam update that
 * renames a method should degrade the feature, not break the whole plugin.
 *
 * Split by subject, the way `src/backend/` and the Plugin class already are.
 * This was one 713-line module holding shortcuts, artwork, collections, hidden
 * apps and launching -- four unrelated jobs sharing nothing but the fact that
 * Steam is on the other end of them.
 *
 * Re-exported from here so every importer keeps writing `from "./steam"`, and
 * so what this plugin does to somebody's Steam library can still be read as one
 * list when that is what is wanted.
 *
 * `client.ts` is deliberately not among them: it holds the injected globals,
 * and nothing outside this directory should be reaching for one.
 */
export * from "./shortcuts";
export * from "./layout";
export * from "./artwork";
export * from "./collections";
export * from "./focus";
// contextMenu is deliberately NOT re-exported, for the same reason client.ts
// is not: it imports @decky/ui's webpack helpers, which initialise against
// `window.webpackChunksteamui` the moment the module loads. That global does
// not exist under Node, so a re-export here takes every test that imports
// from "./steam" down with it -- five of them, on the first run after it was
// added. Import it by path from the one place that patches Steam.
