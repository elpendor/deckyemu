/**
 * The line to the DeckyEmu service.
 *
 * The service holds a debugger session on this page and gives it one function,
 * `__deckyemuHost`, through `Runtime.addBinding`: a call to it reaches that
 * session and nothing else, so there is no port to find and no token to guard.
 * Replies and events come back the same way, as `Runtime.evaluate` calls into
 * the functions below.
 *
 * A service that restarts leaves calls in flight unanswered; it says so when it
 * reattaches, and they are rejected rather than left hanging.
 */

type Listener = (...args: any[]) => unknown;

interface Wire {
  reply?(id: number, ok: boolean, value: unknown): void;
  event?(name: string, args: unknown[]): void;
  reconnected?(): void;
}

const pending = new Map<number, { resolve(value: unknown): void; reject(error: Error): void }>();
const listeners = new Map<string, Set<Listener>>();
let next = 0;

function wire(): Wire & Record<string, unknown> {
  const w = window as unknown as { __deckyemu?: Wire & Record<string, unknown> };
  return (w.__deckyemu ??= {} as Wire & Record<string, unknown>);
}

/** Call `method` on the service with `args`; resolves with what it returned. */
export function call<Return = unknown>(method: string, ...args: unknown[]): Promise<Return> {
  const send = (window as unknown as { __deckyemuHost?: (payload: string) => void }).__deckyemuHost;
  if (!send) return Promise.reject(new Error("DeckyEmu is not connected."));
  const id = ++next;
  return new Promise<Return>((resolve, reject) => {
    pending.set(id, { resolve: resolve as (value: unknown) => void, reject });
    try {
      send(JSON.stringify({ id, method, args }));
    } catch (error) {
      pending.delete(id);
      reject(error instanceof Error ? error : new Error(String(error)));
    }
  });
}

/** `call` bound to one method, so a binding reads like the function it is. */
export function callable<Args extends unknown[] = [], Return = void>(method: string) {
  return (...args: Args) => call<Return>(method, ...args);
}

export function addEventListener<Args extends unknown[] = []>(
  event: string,
  listener: (...args: Args) => unknown,
): (...args: Args) => unknown {
  let set = listeners.get(event);
  if (!set) listeners.set(event, (set = new Set()));
  set.add(listener as Listener);
  return listener;
}

export function removeEventListener<Args extends unknown[] = []>(
  event: string,
  listener: (...args: Args) => unknown,
): void {
  listeners.get(event)?.delete(listener as Listener);
}

/** Wire the service's side of the channel to this bundle. */
export function connect(): void {
  const w = wire();
  w.reply = (id, ok, value) => {
    const waiting = pending.get(id);
    if (!waiting) return;
    pending.delete(id);
    if (ok) waiting.resolve(value);
    else waiting.reject(new Error(String(value)));
  };
  w.event = (name, args) => {
    for (const listener of [...(listeners.get(name) ?? [])]) {
      try {
        listener(...(args ?? []));
      } catch (error) {
        console.error(`[deckyemu] a listener for ${name} failed`, error);
      }
    }
  };
  w.reconnected = () => {
    for (const [id, waiting] of pending) {
      pending.delete(id);
      waiting.reject(new Error("DeckyEmu restarted before it answered."));
    }
  };
}
