import { useId, useState } from 'react';
import { focusRing, input } from './classes';
import { Icon } from './ui';

// Labelled input. Error text is linked via aria-describedby and rendered in
// rose-300 (status-danger) below the field.
export function Field({ label, error, hint, id: idProp, className = '', inputRef, trailing, ...props }) {
  const autoId = useId();
  const id = idProp || autoId;
  const errId = `${id}-error`;
  const hintId = `${id}-hint`;
  const describedBy = [error ? errId : null, hint ? hintId : null].filter(Boolean).join(' ') || undefined;
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1.5 block text-body font-medium text-fg-secondary">
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          ref={inputRef}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          className={`${input} ${trailing ? 'pr-12' : ''}`}
          {...props}
        />
        {trailing}
      </div>
      {hint && !error && (
        <div id={hintId} className="mt-1.5 text-caption text-fg-muted">
          {hint}
        </div>
      )}
      {error && (
        <p id={errId} className="mt-1.5 text-sm text-status-danger">
          {error}
        </p>
      )}
    </div>
  );
}

export function PasswordField(props) {
  const [show, setShow] = useState(false);
  return (
    <Field
      {...props}
      type={show ? 'text' : 'password'}
      trailing={
        <button
          type="button"
          onClick={() => setShow((s) => !s)}
          aria-label={show ? 'Hide password' : 'Show password'}
          aria-pressed={show}
          className={`absolute inset-y-0 right-1 my-auto flex size-9 items-center justify-center rounded-md text-fg-muted hover:text-fg ${focusRing}`}
        >
          <Icon name={show ? 'eyeOff' : 'eye'} className="size-5" />
        </button>
      }
    />
  );
}
