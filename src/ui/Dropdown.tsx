import { type ReactNode } from "react";

import { DialogButton, Focusable, playNavSound, showModal } from "../steamui/base";
import { Field } from "./Field";
import { DialogHeader, ModalRoot } from "./Modal";
import { styled } from "./styles";

export interface SingleDropdownOption {
  data: any;
  label: ReactNode;
}

export interface DropdownOption {
  label: ReactNode;
  data?: any;
  options?: DropdownOption[];
}

export interface DropdownProps {
  rgOptions: DropdownOption[];
  selectedOption: any;
  onChange?: (option: SingleDropdownOption) => void;
  disabled?: boolean;
  menuLabel?: string;
  strDefaultLabel?: ReactNode;
}

function flat(options: DropdownOption[]): SingleDropdownOption[] {
  return options.flatMap((option) => (option.options ? flat(option.options) : [option as SingleDropdownOption]));
}

function OptionList({ options, selected, title, onPick, closeModal }: {
  options: DropdownOption[];
  selected: any;
  title?: ReactNode;
  onPick: (option: SingleDropdownOption) => void;
  closeModal?: () => void;
}) {
  const row = (option: DropdownOption, key: string): ReactNode =>
    option.options ? (
      <div key={key}>
        <div className="dek-option-group">{option.label}</div>
        {option.options.map((child, index) => row(child, `${key}.${index}`))}
      </div>
    ) : (
      <Field
        key={key}
        focusable
        bottomSeparator="none"
        label={option.label}
        autoFocus={option.data === selected}
        onActivate={() => {
          // Steam's sound for A on an onClick, which onActivate replaces.
          playNavSound("DefaultOk");
          closeModal?.();
          onPick(option as SingleDropdownOption);
        }}
        onClick={() => { closeModal?.(); onPick(option as SingleDropdownOption); }}
      >
        {option.data === selected ? <span aria-label="selected">✓</span> : null}
      </Field>
    );
  return (
    <ModalRoot closeModal={closeModal}>
      {title && <DialogHeader>{title}</DialogHeader>}
      <Focusable className="dek-option-list" ref={styled}>
        {options.map((option, index) => row(option, String(index)))}
      </Focusable>
    </ModalRoot>
  );
}

/**
 * A button showing the chosen option, opening the whole list in a dialog. Not
 * Steam's popup menu: that is the control Steam has rebuilt most often.
 */
export function Dropdown({ rgOptions, selectedOption, onChange, disabled, menuLabel, strDefaultLabel }: DropdownProps) {
  const chosen = flat(rgOptions).find((option) => option.data === selectedOption);
  const open = () => {
    showModal(
      <OptionList options={rgOptions} selected={selectedOption} title={menuLabel}
        onPick={(option) => onChange?.(option)} />,
    );
  };
  return (
    <div className="dek-dropdown" ref={styled}>
      <DialogButton disabled={disabled} onClick={open}>
        <span>{chosen?.label ?? strDefaultLabel ?? "Choose"}</span>
        <span aria-hidden="true">▾</span>
      </DialogButton>
    </div>
  );
}

export interface DropdownItemProps extends DropdownProps {
  label?: ReactNode;
  description?: ReactNode;
  layout?: "below" | "inline";
  bottomSeparator?: "standard" | "thick" | "none";
}

export function DropdownItem({ label, description, layout = "inline", bottomSeparator, ...dropdown }: DropdownItemProps) {
  return (
    <Field label={label} description={description} childrenLayout={layout}
      bottomSeparator={bottomSeparator} disabled={dropdown.disabled}>
      <Dropdown menuLabel={typeof label === "string" ? label : undefined} {...dropdown} />
    </Field>
  );
}
