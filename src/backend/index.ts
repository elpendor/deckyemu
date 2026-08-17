/**
 * Every `callable()` binding and its types, in seven files by subject.
 *
 * This was one 1,175-line module. It is the contract between the two halves --
 * a name here has to match a method on the Plugin class, checked by the suite --
 * and it grew to the point where finding the firmware endpoints meant scrolling
 * past the PlayStation ones.
 *
 * Split to match the backend, which went the same way: plugin_emulators,
 * plugin_firmware, plugin_packages and the rest. Looking for an endpoint from
 * either side now lands in a file with the same name.
 *
 * Re-exported from here so every importer keeps writing `from "./backend"`, and
 * so the contract can still be read as one list when that is what is wanted.
 * Nothing imports a file below directly, which is what makes moving a
 * declaration between them cost nothing.
 *
 * `games.ts` had drifted into holding two subjects that are not adding a game:
 * installing RetroArch and its cores, and signing in to RetroAchievements. The
 * tell was a docstring for `canUninstallRetroArch` that had come adrift and was
 * sitting four declarations away from it. Both now have the file the backend
 * already had -- installer.py and plugin_accounts.py -- so looking for an
 * endpoint from either side still lands in a file with the same name.
 */
export * from "./accounts";
export * from "./emulators";
export * from "./firmware";
export * from "./games";
export * from "./library";
export * from "./packages";
export * from "./retroarch";
