import { forwardRef, useState, type FC, type ReactNode } from "react";

import { DialogButtonPrimary, DialogButtonSecondary, Focusable } from "../steamui/base";
import { styled } from "./styles";

type Any = Record<string, any>;

const join = (...names: Array<string | false | undefined>) => names.filter(Boolean).join(" ");

/**
 * Steam's dialog layout pieces. Its own are plain elements carrying these
 * global class names, which have not changed in years, so nothing is looked up.
 */
function classed(name: string, focusable: boolean): FC<Any> {
  const component = forwardRef<unknown, Any>(({ className, ...rest }, ref) =>
    focusable
      ? <Focusable {...rest} ref={ref} className={join(name, className)} />
      : <div {...rest} ref={ref as never} className={join(name, className)} />,
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
  onCancel?: () => unknown;
  bAllowFullSize?: boolean;
  bDestructiveWarning?: boolean;
  bDisableBackgroundDismiss?: boolean;
  bHideCloseIcon?: boolean;
  className?: string;
  children?: ReactNode;
}

/**
 * A dialog's frame, shown through Steam's modal manager (`showModal`), which
 * hands it `closeModal`. B, and a tap outside the box, cancel: `onCancel`
 * runs, and the dialog closes unless it returned something truthy -- the rule
 * Steam's own frame follows.
 */
export function ModalRoot({
  closeModal, onCancel, bAllowFullSize, bDisableBackgroundDismiss, className, children,
  bDestructiveWarning: _destructive, bHideCloseIcon: _noClose, onOK: _ok, ...rest
}: ModalRootProps) {
  const cancel = () => {
    if (!onCancel?.()) closeModal?.();
  };
  return (
    <Focusable className="dek-modal" onCancel={cancel}>
      <div className="dek-modal-backdrop" ref={styled}
        onClick={bDisableBackgroundDismiss ? undefined : cancel} />
      <Focusable
        {...rest}
        role="dialog"
        className={join(
          "DialogContent _DialogLayout GenericDialogBase GenericConfirmDialog",
          bAllowFullSize && "DialogContentFullSize",
          className,
        )}
      >
        <div className="DialogContent_InnerWidth">{children}</div>
      </Focusable>
    </Focusable>
  );
}

export interface ConfirmModalProps extends ModalRootProps {
  strTitle?: ReactNode;
  strDescription?: ReactNode;
  strOKButtonText?: ReactNode;
  strCancelButtonText?: ReactNode;
  strMiddleButtonText?: ReactNode;
  onOK?: () => unknown;
  onMiddleButton?: () => void;
  bAlertDialog?: boolean;
  bOKDisabled?: boolean;
  bCancelDisabled?: boolean;
  bMiddleDisabled?: boolean;
}

/**
 * Title, text and buttons, laid out with the same global classes as Steam's.
 * OK first and focused, as Steam has it; an alert has OK alone.
 */
export function ConfirmModal(props: ConfirmModalProps) {
  const {
    strTitle, strDescription, strOKButtonText, strCancelButtonText, strMiddleButtonText,
    onOK, onCancel, onMiddleButton, bAlertDialog, bOKDisabled, bCancelDisabled,
    bMiddleDisabled, closeModal, children, ...rest
  } = props;
  const [busy, setBusy] = useState(false);

  const ok = async () => {
    if (bOKDisabled || busy) return;
    setBusy(true);
    try {
      await onOK?.();
    } finally {
      setBusy(false);
    }
    closeModal?.();
  };
  const cancel = () => {
    onCancel?.();
    closeModal?.();
  };
  const middle = () => {
    onMiddleButton?.();
    closeModal?.();
  };

  let buttons: ReactNode;
  if (bAlertDialog) {
    buttons = (
      <DialogButtonPrimary onClick={ok} disabled={bOKDisabled}>
        {strOKButtonText ?? "Close"}
      </DialogButtonPrimary>
    );
  } else {
    buttons = (
      <Focusable
        className={strMiddleButtonText
          ? "DialogThreeColLayout _DialogColLayout"
          : "DialogTwoColLayout _DialogColLayout"}
        flow-children="row"
      >
        <DialogButtonPrimary onClick={ok} disabled={bOKDisabled}>
          {strOKButtonText ?? "OK"}
        </DialogButtonPrimary>
        {strMiddleButtonText && (
          <DialogButtonSecondary onClick={middle} disabled={bMiddleDisabled}>
            {strMiddleButtonText}
          </DialogButtonSecondary>
        )}
        <DialogButtonSecondary onClick={cancel} disabled={bCancelDisabled}>
          {strCancelButtonText ?? "Cancel"}
        </DialogButtonSecondary>
      </Focusable>
    );
  }

  return (
    <ModalRoot {...rest} closeModal={closeModal} onCancel={() => { onCancel?.(); return false; }}>
      <DialogHeader role="heading" aria-level={2}>{strTitle || " "}</DialogHeader>
      <DialogBody>
        <DialogBodyText>
          {strDescription}
          {children}
        </DialogBodyText>
        <DialogFooter>{buttons}</DialogFooter>
      </DialogBody>
    </ModalRoot>
  );
}
