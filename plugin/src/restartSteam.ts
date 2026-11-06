/**
 * Restart Steam, as the loader's own prompt does. The argument is required: the
 * call with none does nothing.
 */
export function restartSteam(): void {
  try {
    (window as unknown as { SteamClient: { User: { StartRestart: (force: boolean) => void } } })
      .SteamClient.User.StartRestart(false);
  } catch (error) {
    console.error("[deckyemu] could not restart Steam", error);
  }
}
