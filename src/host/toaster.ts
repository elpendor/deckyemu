/**
 * Short confirmations, drawn over the Game Mode window.
 *
 * Plain DOM in that window's document rather than a React tree: a toast has to
 * outlive whichever panel raised it, and this needs nothing from Steam beyond
 * the window itself. Only for confirming what just happened -- anything to read
 * or act on is a dialog.
 */

import { mainWindow } from "../steamui/navigation";

export interface Toast {
  title: string;
  body?: string;
  /** Milliseconds. */
  duration?: number;
}

const STACK_ID = "deckyemu-toasts";

function stackIn(doc: Document): HTMLElement {
  let stack = doc.getElementById(STACK_ID);
  if (!stack) {
    stack = doc.createElement("div");
    stack.id = STACK_ID;
    // Bottom right, above the button bar, where Steam puts its own toasts:
    // centred, a confirmation covered the very thing it confirmed.
    Object.assign(stack.style, {
      position: "fixed",
      right: "16px",
      bottom: "72px",
      alignItems: "flex-end",
      display: "flex",
      flexDirection: "column",
      gap: "8px",
      zIndex: "100000",
      pointerEvents: "none",
    });
    doc.body.appendChild(stack);
  }
  return stack;
}

// Only confirmations come here, so a glance is enough.
function toast({ title, body, duration = 2500 }: Toast): void {
  try {
    const doc: Document | undefined = mainWindow()?.BrowserWindow?.document;
    if (!doc?.body) {
      console.log(`[deckyemu] ${title}${body ? ": " + body : ""}`);
      return;
    }
    const card = doc.createElement("div");
    Object.assign(card.style, {
      background: "rgba(23, 29, 37, 0.96)",
      color: "#dcdedf",
      borderRadius: "4px",
      padding: "8px 12px",
      maxWidth: "320px",
      boxShadow: "0 4px 16px rgba(0, 0, 0, 0.5)",
      fontSize: "13px",
      transition: "opacity 200ms",
    });
    const heading = doc.createElement("div");
    heading.textContent = title;
    heading.style.fontWeight = "bold";
    card.appendChild(heading);
    if (body) {
      const text = doc.createElement("div");
      text.textContent = body;
      text.style.opacity = "0.8";
      text.style.marginTop = "2px";
      card.appendChild(text);
    }
    stackIn(doc).appendChild(card);
    setTimeout(() => {
      card.style.opacity = "0";
      setTimeout(() => card.remove(), 250);
    }, duration);
  } catch (error) {
    console.error("[deckyemu] could not show a toast", error);
  }
}

export const toaster = { toast };
