/**
 * Steam's own controls, looked up in its UI build the first time each renders.
 *
 * Only the controls that have never broken across Steam updates are taken from
 * Steam; the rest are DeckyEmu's own, in src/ui. Every export here is Steam's
 * component when its anchor is found, and a plain stand-in when it is not: a
 * Steam update that moves one control leaves that control looking plainer,
 * never a blank panel or a thrown render. `report()` in webpack.ts names
 * whatever was missed.
 *
 * Props are Steam's. The panel was written against these same components, so
 * what it passes is what they take; the types below describe only the part of
 * each that the panel uses.
 */

import {
  createElement,
  forwardRef,
  type CSSProperties,
  type ChangeEvent,
  type FC,
  type ReactNode,
} from "react";

import { findExport, findModule, noteLookup } from "./webpack";

type Any = Record<string, any>;

const everyLookup: Array<() => unknown> = [];

/** Have `resolveAll` run `lookup` too. */
export function registerLookup(lookup: () => unknown): void {
  everyLookup.push(lookup);
}

/** Run every lookup now, so the report names everything that is missing. */
export function resolveAll(): void {
  for (const lookup of everyLookup) lookup();
}

/** A lookup that runs once, remembering a miss as well as a hit. */
function lazy<T>(lookup: () => T | null): () => T | null {
  let done = false;
  let value: T | null = null;
  const run = () => {
    if (!done) {
      try {
        value = lookup();
      } catch (error) {
        console.error("[deckyemu] lookup failed", error);
        value = null;
      }
      done = true;
    }
    return value;
  };
  everyLookup.push(run);
  return run;
}

/**
 * A component that renders Steam's `lookup()` when there is one and
 * `fallback(props)` when there is not. Refs pass through to Steam's.
 */
function steam<P>(name: string, lookup: () => unknown, fallback: (props: P) => ReactNode): FC<P> {
  const get = lazy(lookup);
  const component = forwardRef<unknown, P>((props, ref) => {
    const found = get();
    if (!found) return fallback(props as P) as never;
    return createElement(found as never, (ref ? { ...props, ref } : props) as never);
  });
  component.displayName = name;
  return component as unknown as FC<P>;
}

const bridge = () =>
  (window as unknown as { __deckyemu?: { steam?: { Focusable?: unknown } } }).__deckyemu;

// --- the modules ------------------------------------------------------------

const fieldModule = lazy(() => findModule("field module", ['"#Field_MoreInfo_Action"', "childrenContainerWidth"]));
const controls = lazy(() => findModule("gamepad controls", ['"OnToggleChange"', '"DialogDropDown"']));
const buttons = lazy(() => findModule("dialog buttons", ['"DialogButton","_DialogLayout","Primary"']));

const isRef = (value: unknown) => !!value && typeof value === "object" && "render" in (value as object);

// --- layout
// -------------------------------------------------------------------

export interface FocusableProps extends Any {
  children?: ReactNode;
  className?: string;
  style?: CSSProperties;
  "flow-children"?: string;
  focusable?: boolean;
  noFocusRing?: boolean;
  onActivate?: (event: unknown) => void;
  onCancel?: (event: unknown) => void;
  onButtonDown?: (event: GamepadEvent) => void;
  onGamepadDirection?: (event: GamepadEvent) => void;
  fnCanTakeFocus?: () => boolean;
}

export const Focusable = steam<FocusableProps>(
  "Focusable",
  () => {
    const captured = bridge()?.steam?.Focusable;
    if (captured) {
      noteLookup("Focusable", true);
      return captured;
    }
    const module = findModule("focusable module", ['"gpfocuswithin"', "flow-children"]);
    return findExport("Focusable", module, (_value, src) => src.includes('"gpfocuswithin"'));
  },
  ({ children, className, style }) => <div className={className} style={style}>{children}</div>,
);

// --- controls
// -----------------------------------------------------------------

export interface TextFieldProps extends Any {
  label?: ReactNode;
  description?: ReactNode;
  value?: string;
  disabled?: boolean;
  bIsPassword?: boolean;
  bShowClearAction?: boolean;
  onChange?: (event: ChangeEvent<HTMLInputElement>) => void;
  onBlur?: (event: unknown) => void;
  style?: CSSProperties;
  layout?: "below" | "inline";
}

const SteamTextField = steam<TextFieldProps>(
  "TextField",
  () => findExport("TextField", fieldModule(), (v, src) => isRef(v) && src.includes('childrenContainerWidth:"fixed"')),
  ({ label, value, disabled, bIsPassword, onChange, onBlur, style }) => (
    <label style={{ display: "block", padding: "8px 0" }}>
      {label}
      <input type={bIsPassword ? "password" : "text"} value={value} disabled={disabled}
        onChange={onChange} onBlur={onBlur as never} style={{ width: "100%", ...style }} />
    </label>
  ),
);

// Steam's default puts the label beside a fixed-width input, which overflows
// the 300px Quick Access panel and scrolls it sideways on focus.
export const TextField: FC<TextFieldProps> = (props) => <SteamTextField layout="below" {...props} />;

export interface ToggleFieldProps extends Any {
  label?: ReactNode;
  description?: ReactNode;
  checked: boolean;
  disabled?: boolean;
  onChange?: (checked: boolean) => void;
}

export const ToggleField = steam<ToggleFieldProps>(
  "ToggleField",
  () => findExport("ToggleField", controls(), (_v, src) => src.includes("OnToggleChange(")),
  ({ label, description, checked, disabled, onChange }) => (
    <label style={{ display: "block", padding: "8px 0" }}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange?.(e.target.checked)} />
      {label}
      {description && <div style={{ fontSize: "12px", opacity: 0.7 }}>{description}</div>}
    </label>
  ),
);

// --- buttons and dialogs
// ---------------------------------------------------------

export interface DialogButtonProps extends Any {
  disabled?: boolean;
  onClick?: (event: unknown) => void;
  style?: CSSProperties;
  className?: string;
  children?: ReactNode;
}

const buttonFallback = ({ disabled, onClick, style, children }: DialogButtonProps) => (
  <button disabled={disabled} onClick={onClick} style={style}>{children}</button>
);

export const DialogButtonSecondary = steam<DialogButtonProps>(
  "DialogButtonSecondary",
  () => findExport("DialogButtonSecondary", buttons(), (v, src) => isRef(v) && src.includes('"Secondary"')),
  buttonFallback,
);
export const DialogButton = DialogButtonSecondary;

export const DialogButtonPrimary = steam<DialogButtonProps>(
  "DialogButtonPrimary",
  () => findExport("DialogButtonPrimary", buttons(), (v, src) => isRef(v) && src.includes('"Primary"')),
  buttonFallback,
);

// --- the side menu, and what it shows
// ---------------------------------------------------

/** Steam's controller button numbers, as its gamepad events carry them. */
export const GamepadButton = new Proxy({} as Record<string, number>, {
  get(_target, key: string) {
    const module = gamepadButtons();
    return (module as Record<string, number> | null)?.[key];
  },
});

const gamepadButtons = lazy(() => {
  const module = findModule("gamepad buttons", ['DIR_UP=9]="DIR_UP"']);
  return findExport<Record<string, number>>("GamepadButton", module, (value) => {
    const v = value as Record<string, number> | null;
    return !!v && typeof v === "object" && v.OK === 1 && v.DIR_UP === 9;
  });
});

export interface GamepadEvent extends CustomEvent {
  detail: { button: number; is_repeat?: boolean; source?: number };
}

/**

 * The Quick Access menu's own class names. Empty strings if Steam moved them.

 */
export const quickAccessMenuClasses = new Proxy({} as Record<string, string>, {
  get(_target, key: string) {
    return (qamClasses() as Record<string, string> | null)?.[key] ?? "";
  },
});

const qamClasses = lazy(() =>
  findModule("quick access classes", ['QuickAccessMenuEmbeddedContainer:"', 'TabGroupPanel:"', 'Title:"']),
);
