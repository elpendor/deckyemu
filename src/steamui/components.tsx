/**
 * Steam's own controls, looked up in its UI build the first time each renders.
 *
 * Every export here is Steam's component when its anchor is found, and a plain
 * stand-in when it is not: a Steam update that moves one control leaves that
 * control looking plainer, never a blank panel or a thrown render. `report()`
 * in webpack.ts names whatever was missed.
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
const sections = lazy(() => findModule("panel sections", [".PanelSectionTitle", ".PanelSectionRow)", ".spinner&&"]));
const icons = lazy(() => findModule("icons", ["ABXYButton:()=>", "Spinner:()=>"]));

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

export interface PanelSectionProps {
  title?: ReactNode;
  spinner?: boolean;
  children?: ReactNode;
}

export const PanelSection = steam<PanelSectionProps>(
  "PanelSection",
  () => findExport("PanelSection", sections(), (_v, src) => src.includes("PanelSectionTitle")),
  ({ title, children }) => (
    <div style={{ padding: "8px 0" }}>
      {title && <div style={{ fontWeight: "bold", textTransform: "uppercase", padding: "4px 0" }}>{title}</div>}
      {children}
    </div>
  ),
);

export const PanelSectionRow = steam<{ children?: ReactNode }>(
  "PanelSectionRow",
  () => findExport("PanelSectionRow", sections(), (_v, src) => !src.includes("PanelSectionTitle")),
  ({ children }) => <div>{children}</div>,
);

export interface FieldProps extends Any {
  label?: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  children?: ReactNode;
  bottomSeparator?: "standard" | "thick" | "none";
  childrenLayout?: "below" | "inline";
  childrenContainerWidth?: "min" | "max" | "fixed";
  focusable?: boolean;
  onActivate?: (event: unknown) => void;
  onClick?: (event: unknown) => void;
}

export const Field = steam<FieldProps>(
  "Field",
  () => findExport("Field", fieldModule(), (v, src) => isRef(v) && src.includes("accessibilityId:null")),
  ({ label, description, children }) => (
    <div style={{ padding: "8px 0" }}>
      {label && <div>{label}</div>}
      {description && <div style={{ fontSize: "12px", opacity: 0.7 }}>{description}</div>}
      {children}
    </div>
  ),
);

export interface ButtonItemProps extends Any {
  label?: ReactNode;
  description?: ReactNode;
  layout?: "below" | "inline";
  disabled?: boolean;
  onClick?: (event: unknown) => void;
  children?: ReactNode;
}

export const ButtonItem = steam<ButtonItemProps>(
  "ButtonItem",
  () =>
    findExport("ButtonItem", fieldModule(), (v, src) =>
      isRef(v) && src.includes("fieldChildren") && src.includes("childrenLayout:"),
    ),
  ({ label, description, disabled, onClick, children }) => (
    <div style={{ padding: "8px 0" }}>
      {label && <div>{label}</div>}
      <button disabled={disabled} onClick={onClick} style={{ width: "100%" }}>{children}</button>
      {description && <div style={{ fontSize: "12px", opacity: 0.7 }}>{description}</div>}
    </div>
  ),
);

export const Spinner = steam<{ style?: CSSProperties }>(
  "Spinner",
  () => {
    const found = (icons() as Any | null)?.Spinner ?? null;
    noteLookup("Spinner", !!found);
    return found;
  },
  ({ style }) => <div style={{ ...style, opacity: 0.6 }}>...</div>,
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

export interface SingleDropdownOption {
  data: any;
  label: ReactNode;
}
export interface DropdownOption {
  label: ReactNode;
  data?: any;
  options?: DropdownOption[];
}

export interface DropdownProps extends Any {
  rgOptions: DropdownOption[];
  selectedOption: any;
  onChange?: (option: SingleDropdownOption) => void;
  disabled?: boolean;
  menuLabel?: string;
  strDefaultLabel?: string;
}

function flatOptions(options: DropdownOption[]): SingleDropdownOption[] {
  return options.flatMap((option) =>
    option.options ? flatOptions(option.options) : [option as SingleDropdownOption],
  );
}

function selectFallback({ rgOptions, selectedOption, onChange, disabled }: DropdownProps) {
  const flat = flatOptions(rgOptions);
  return (
    <select disabled={disabled} value={flat.findIndex((o) => o.data === selectedOption)}
      onChange={(e) => onChange?.(flat[Number(e.target.value)])}>
      {flat.map((option, index) => <option key={index} value={index}>{String(option.label)}</option>)}
    </select>
  );
}

export const Dropdown = steam<DropdownProps>(
  "Dropdown",
  () => findExport("Dropdown", controls(), (_v, src) => src.includes("SetSelectedOption(")),
  selectFallback,
);

export interface DropdownItemProps extends DropdownProps {
  label?: ReactNode;
  description?: ReactNode;
  layout?: "below" | "inline";
}

export const DropdownItem = steam<DropdownItemProps>(
  "DropdownItem",
  () => findExport("DropdownItem", controls(), (_v, src) => src.includes('"DropDownField"')),
  (props) => (
    <label style={{ display: "block", padding: "8px 0" }}>
      {props.label}
      {selectFallback(props)}
      {props.description && <div style={{ fontSize: "12px", opacity: 0.7 }}>{props.description}</div>}
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

/**
 * The dialog layout pieces. Steam's are plain elements carrying these global
 * class names, so they are written out here rather than looked up: there is
 * nothing in them to find, and a class name is the most stable thing Steam has.
 */
function classed(name: string, focusable: boolean) {
  const component = forwardRef<unknown, Any>(({ className, ...rest }, ref) =>
    focusable
      ? <Focusable {...rest} ref={ref} className={[name, className].filter(Boolean).join(" ")} />
      : <div {...rest} ref={ref as never} className={[name, className].filter(Boolean).join(" ")} />,
  );
  component.displayName = name;
  return component as unknown as FC<Any>;
}

export const DialogHeader = classed("DialogHeader", false);
export const DialogBody = classed("DialogBody", true);
export const DialogBodyText = classed("DialogBodyText", false);
export const DialogFooter = classed("DialogFooter", false);

export interface ModalRootProps extends Any {
  closeModal?: () => void;
  onCancel?: () => void;
  onOK?: () => void;
  bAllowFullSize?: boolean;
  bDestructiveWarning?: boolean;
  bDisableBackgroundDismiss?: boolean;
  bHideCloseIcon?: boolean;
  className?: string;
  children?: ReactNode;
}

export const ModalRoot = steam<ModalRootProps>(
  "ModalRoot",
  () => {
    const module = findModule("modal root", ['"GenericConfirmDialog"', '"GenericDialogBase"']);
    return findExport("ModalRoot", module, (_v, src) => src.includes('"GenericDialogBase"'));
  },
  ({ children, closeModal, onCancel }) => (
    <div style={{ position: "fixed", inset: "40px", background: "#1a1d23", padding: "24px", overflow: "auto" }}>
      {children}
      <button onClick={() => (onCancel ?? closeModal)?.()}>Close</button>
    </div>
  ),
);

export interface ConfirmModalProps extends ModalRootProps {
  strTitle?: ReactNode;
  strDescription?: ReactNode;
  strOKButtonText?: ReactNode;
  strCancelButtonText?: ReactNode;
  bAlertDialog?: boolean;
  bOKDisabled?: boolean;
}

export const ConfirmModal = steam<ConfirmModalProps>(
  "ConfirmModal",
  () => {
    const module = findModule("confirm modal", ['"#Error_GenericFailureDescription"', "strMiddleButtonText"]);
    return findExport("ConfirmModal", module, (_v, src) => src.includes("strMiddleButtonText"));
  },
  ({ strTitle, strDescription, children, onOK, onCancel, closeModal, strOKButtonText, strCancelButtonText, bAlertDialog }) => (
    <div style={{ position: "fixed", inset: "80px", background: "#1a1d23", padding: "24px" }}>
      <h2>{strTitle}</h2>
      <div>{strDescription}</div>
      {children}
      <button onClick={() => { onOK?.(); closeModal?.(); }}>{strOKButtonText ?? "OK"}</button>
      {!bAlertDialog && <button onClick={() => { onCancel?.(); closeModal?.(); }}>{strCancelButtonText ?? "Cancel"}</button>}
    </div>
  ),
);

// --- composites
// ------------------------------------------------------------------

export interface Tab {
  id: string;
  title: ReactNode;
  content: ReactNode;
}

export interface TabsProps extends Any {
  tabs: Tab[];
  activeTab: string;
  onShowTab: (id: string) => void;
  autoFocusContents?: boolean;
}

const tabsLookup = lazy(() => {
  const module = findModule("tabs", ["cancelSkipTabHeader", "belowHeaderTabsContent"]);
  // An observer, so its own source is a generic wrapper with nothing to match;
  // it is the module's one memo export, and the module is pinned by its props.
  return findExport("Tabs", module, (v) => {
    const memo = v as { type?: unknown; compare?: unknown } | null;
    return !!memo && typeof memo === "object" && typeof memo.type === "function" && "compare" in memo;
  });
});

export const Tabs = steam<TabsProps>(
  "Tabs",
  tabsLookup,
  ({ tabs, activeTab, onShowTab }) => (
    <div>
      <Focusable flow-children="row" style={{ display: "flex", gap: "8px" }}>
        {tabs.map((tab) => (
          <DialogButton key={tab.id} onClick={() => onShowTab(tab.id)} style={{ opacity: tab.id === activeTab ? 1 : 0.6 }}>
            {tab.title}
          </DialogButton>
        ))}
      </Focusable>
      {tabs.find((tab) => tab.id === activeTab)?.content}
    </div>
  ),
);

export interface SidebarPage {
  title: ReactNode;
  content: ReactNode;
  icon?: ReactNode;
  route?: string;
  identifier?: string;
  hideTitle?: boolean;
}

const pagedSettings = lazy(() => findExport("SidebarNavigation", controls(), (_v, src) => src.includes('"PagedSettings"')));

export { pagedSettings as pagedSettingsComponent };

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
