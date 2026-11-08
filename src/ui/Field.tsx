import { forwardRef, type CSSProperties, type ReactNode } from "react";

import { DialogButton, Focusable } from "../steamui/base";
import { styled } from "./styles";

type Any = Record<string, any>;

const join = (...names: Array<string | false | undefined>) => names.filter(Boolean).join(" ");

export interface PanelSectionProps {
  title?: ReactNode;
  spinner?: boolean;
  children?: ReactNode;
}

export function PanelSection({ title, children }: PanelSectionProps) {
  return (
    <div className="dek-section" ref={styled}>
      {title && (
        <div className="dek-section-title">
          <div>{title}</div>
        </div>
      )}
      {children}
    </div>
  );
}

export function PanelSectionRow({ children }: { children?: ReactNode }) {
  return <div className="dek-row">{children}</div>;
}

export interface FieldProps extends Any {
  label?: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  children?: ReactNode;
  bottomSeparator?: "standard" | "thick" | "none";
  childrenLayout?: "below" | "inline";
  childrenContainerWidth?: "min" | "max" | "fixed";
  focusable?: boolean;
  highlightOnFocus?: boolean;
  disabled?: boolean;
  className?: string;
  style?: CSSProperties;
  onActivate?: (event: unknown) => void;
  onClick?: (event: unknown) => void;
}

/**
 * A row with a label, a description and controls: Steam's Field, laid out with
 * its measured values. The root is a Focusable either way, so it highlights
 * when focus is anywhere inside it, as Steam's does.
 */
export const Field = forwardRef<HTMLDivElement, FieldProps>(function Field(props, ref) {
  const {
    label, description, icon, children, bottomSeparator = "standard",
    childrenLayout = "inline", focusable, highlightOnFocus = true, disabled,
    className, childrenContainerWidth: _width, ...rest
  } = props;
  const below = childrenLayout === "below";
  const classes = join(
    "dek-field",
    bottomSeparator === "standard" && "dek-sep",
    bottomSeparator === "thick" && "dek-sep-thick",
    highlightOnFocus && "dek-highlight",
    below && "dek-below",
    disabled && "dek-disabled",
    className,
  );
  const hasLabel = label !== undefined && label !== null && label !== "";
  return (
    <Focusable {...rest} ref={ref} className={classes} focusable={!!focusable && !disabled}>
      {/* The stylesheet goes in from a plain element: Steam's Focusable is
          not known to hand its ref to the DOM. */}
      <div className="dek-field-body" ref={styled}>
        {(hasLabel || (!below && children)) && (
          <div className="dek-label-row">
            {hasLabel && (
              <div className="dek-label">
                {icon}
                {label}
              </div>
            )}
            {!below && children && <div className="dek-inline-children">{children}</div>}
          </div>
        )}
        {below && children && (
          <div className="dek-children">
            <div>{children}</div>
          </div>
        )}
        {description && <div className="dek-desc">{description}</div>}
      </div>
    </Focusable>
  );
});

export interface ButtonItemProps extends Any {
  label?: ReactNode;
  description?: ReactNode;
  layout?: "below" | "inline";
  disabled?: boolean;
  onClick?: (event: unknown) => void;
  bottomSeparator?: "standard" | "thick" | "none";
  children?: ReactNode;
}

/** A Field holding one of Steam's buttons. */
export function ButtonItem({
  label, description, layout = "inline", disabled, onClick, bottomSeparator, children, ...rest
}: ButtonItemProps) {
  return (
    <Field
      label={label}
      description={description}
      childrenLayout={layout}
      bottomSeparator={bottomSeparator}
      disabled={disabled}
    >
      <DialogButton {...rest} disabled={disabled} onClick={onClick}>
        {children}
      </DialogButton>
    </Field>
  );
}

/** A busy indicator, drawn by us: Steam's moved twice in four years. */
export function Spinner({ style }: { style?: CSSProperties }) {
  return <div className="dek-spinner" ref={styled} style={style} role="progressbar" aria-busy="true" />;
}
