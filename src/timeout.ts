/**
 * Guard against backend calls that never answer.
 *
 * Decky reloads a plugin's backend whenever its files change, and any call in
 * flight at that moment is destroyed without a reply -- the loader logs "Task was
 * destroyed but it is pending". The promise then stays pending forever, so a
 * `.finally()` that clears a loading flag never runs and the UI sits on a spinner
 * indefinitely.
 *
 * Every call that gates a loading state should go through this, so a lost reply
 * becomes a visible, retryable error instead.
 */

export class TimeoutError extends Error {
  constructor(ms: number) {
    super(`No reply from the plugin backend after ${ms}ms`);
    this.name = "TimeoutError";
  }
}

/**
 * Call something that might never answer, retrying until it does.
 *
 * The work behind these calls takes single-digit milliseconds, so a slow reply is
 * not a real state -- either it answers promptly or it was dropped by a reload.
 * That makes a short per-attempt timeout with a few quick retries strictly better
 * than one long wait: recovery is invisible instead of a spinner the user has to
 * escape by closing the panel.
 */
export interface RetryOptions {
  attempts?: number;
  /** Per-attempt timeout. */
  ms?: number;
  /** Delay before the first retry; doubles each time, capped. */
  delay?: number;
  maxDelay?: number;
  /** Reports each failed attempt, so the UI can explain the wait. */
  onAttempt?: (attempt: number, attempts: number) => void;
}

/**
 * Timings for a backend call that crosses the network, rather than one that
 * only crosses to the backend.
 *
 * The defaults below assume the work takes single-digit milliseconds, so two
 * seconds without an answer means the reply was dropped by a reload and
 * retrying recovers it. That reasoning does not survive a call to GitHub: two
 * seconds is an ordinary duration there, decky cannot cancel the abandoned
 * attempt, and the retry starts a second request while the first is still
 * running. Measured against a timing-out GitHub, the defaults turned one slow
 * check into 23 requests in fifteen seconds -- against a budget of sixty an
 * hour, which is how being slow becomes being rate-limited.
 *
 * One retry, because the dropped-reply case never needed more than that.
 */
export const OVER_THE_NETWORK: RetryOptions = { attempts: 2, ms: 30000 };

export async function callWithRetry<T>(
  call: () => Promise<T>,
  {
    attempts = 8,
    ms = 2000,
    delay = 300,
    maxDelay = 3000,
    onAttempt,
  }: RetryOptions = {},
): Promise<T> {
  let lastError: unknown;
  let wait = delay;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await withTimeout(call(), ms);
    } catch (error) {
      lastError = error;
      if (attempt >= attempts) break;

      // Backs off because the usual cause is a burst of reloads, not one: a
      // deploy touches many files and decky's watcher reloads on each, so the
      // backend can be unavailable for several seconds in a row.
      console.log(`[deckyemu] backend call attempt ${attempt}/${attempts} failed, retrying`, error);
      onAttempt?.(attempt, attempts);
      await new Promise((resolve) => window.setTimeout(resolve, wait));
      wait = Math.min(wait * 2, maxDelay);
    }
  }

  throw lastError;
}

export function withTimeout<T>(promise: Promise<T>, ms = 8000): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new TimeoutError(ms)), ms);
    promise.then(
      (value) => {
        window.clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        window.clearTimeout(timer);
        reject(error);
      },
    );
  });
}
