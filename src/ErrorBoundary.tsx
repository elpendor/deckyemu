import { DialogButton } from "@decky/ui";
import { Component, type ErrorInfo, type ReactNode } from "react";

import { crashMessage } from "./crashMessage";

/**
 * Stops one broken render from taking anything else down with it.
 *
 * Plugin code is evaluated in SharedJSContext but *renders* into Steam's own
 * React tree -- the Quick Access panel for the panel content, Steam's router for
 * the settings page. React unwinds a thrown render to the nearest boundary
 * above it, so with none of our own the nearest one is whatever Steam or decky
 * happens to have, and everything between here and there is unmounted. That is
 * how a single undefined field in a backend reply becomes an empty Quick Access
 * panel, or an empty screen in Game Mode, with no way back short of restarting
 * Steam.
 *
 * One of these per surface -- the panel, and each tab of the settings page --
 * keeps the failure the size of the thing that failed.
 *
 * What it does not catch: a rejected promise, a throw inside a `setTimeout`, or
 * anything in an event handler. React only routes errors raised during render,
 * in a lifecycle method, or in a constructor. Those still need their own
 * `catch`, which is why the call sites have them.
 */

interface Props {
  children: ReactNode;
  /** Named in the log and shown to the user, so a report says which part broke. */
  where: string;
}

interface State {
  message: string;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { message: "" };

  static getDerivedStateFromError(error: unknown): State {
    // Never empty -- see crashMessage, which is where that invariant is tested.
    // `message` doubles as the "are we in the fallback" flag, so an empty one
    // renders the children that just threw and loops.
    return { message: crashMessage(error) };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    // The component stack is the only thing that names which panel it was, and
    // it is not in the error itself.
    console.error(`[deckyemu] ${this.props.where} failed to render`, error, info?.componentStack);
  }

  private retry = () => this.setState({ message: "" });

  render() {
    if (!this.state.message) return this.props.children;

    /*
     * Plain elements and inline styles on purpose. This is the last thing
     * standing after something already threw, and a fallback that throws in
     * turn is handed straight back up to whatever boundary is above -- which is
     * the failure this class exists to prevent. Steam's own components are
     * resolved by signature at runtime, so they are exactly the wrong thing to
     * depend on here.
     *
     * The one exception is the button: a plain <button> is not reachable with a
     * controller, and an error the user cannot dismiss without restarting Steam
     * is most of the problem. If DialogButton is what broke, this is no worse
     * than having no boundary at all.
     */
    return (
      <div style={{ padding: "12px 16px", display: "flex", flexDirection: "column", gap: "8px" }}>
        <div style={{ fontWeight: "bold" }}>{this.props.where} stopped working</div>
        <div style={{ fontSize: "13px", opacity: 0.7, overflowWrap: "anywhere" }}>
          {this.state.message}
        </div>
        <div style={{ fontSize: "13px", opacity: 0.7 }}>
          Nothing else in the plugin is affected, and nothing has been changed on
          the device. The plugin log has the details.
        </div>
        <DialogButton onClick={this.retry}>Try again</DialogButton>
      </div>
    );
  }
}
