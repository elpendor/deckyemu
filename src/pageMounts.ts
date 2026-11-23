/**
 * How many times the settings page has mounted. The service build reads it to
 * know a reopened page is running the new bundle; see host/reopenPage.ts.
 */
let mounts = 0;

export function notePageMounted(): void {
  mounts += 1;
}

export function pageMounts(): number {
  return mounts;
}
