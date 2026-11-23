/**
 * Put an open settings page back on screen running this bundle's code.
 *
 * The service evaluates a new bundle over the old one on every restart, an
 * update included. Steam's route host keeps the page it already rendered, so
 * a page open at that moment would go on running the replaced code. Stepping
 * off the route and back remounts it. Steam renders a route change a little
 * later than the next frame, so the gap doubles until the new page reports
 * that it mounted.
 */

import { pageMounts } from "../pageMounts";
import { mainWindow } from "../steamui/navigation";

const ROUTE = "/deckyemu";
const AWAY = "/deckyemu-reopening";
const GAPS_MS = [100, 200, 400, 800];
const SETTLE_MS = 600;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export async function reopenPage(): Promise<void> {
  const history = mainWindow()?.m_history;
  const here = history?.location;
  if (!history?.replace || !(here?.pathname === ROUTE || here?.pathname?.startsWith(ROUTE + "/"))) return;
  const back = { pathname: here.pathname, search: here.search, hash: here.hash, state: here.state };
  const before = pageMounts();
  for (const gap of GAPS_MS) {
    history.replace(AWAY);
    await sleep(gap);
    history.replace(back);
    await sleep(SETTLE_MS);
    if (pageMounts() > before) return;
  }
  console.error("[deckyemu] the open settings page did not reload; leave it and open it again");
}
