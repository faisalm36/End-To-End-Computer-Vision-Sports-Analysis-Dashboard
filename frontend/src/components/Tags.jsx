import { useId, useRef, useState } from 'react';
import { usePopover } from '../lib/usePopover';
import { cleanTag, iconForKey, keySuggestions, norm, QUICK_ADD_KEYS, removeTag, tagId, upsertTag, valueSuggestions } from '../lib/tags';
import { btn, focusRing, input } from './classes';
import { Icon } from './ui';

// Shared key/value pill (UI/UX spec: neutral only, never coloured by value).
// variant: static | removable | selectable
export function TagChip({ tag, variant = 'static', onRemove, selected = false, onToggle, count, showIcon = true }) {
  const inner = (
    <>
      {showIcon && <Icon name={iconForKey(tag.key)} className="size-3.5 shrink-0 text-fg-muted" />}
      <span className="text-fg-muted">{tag.key}</span>
      <span aria-hidden="true" className="text-fg-muted">·</span>
      <span className="font-medium text-slate-100">{tag.value}</span>
      {count != null && <span className="font-mono tabular-nums text-fg-muted">{count}</span>}
    </>
  );
  const base = 'inline-flex h-7 max-w-full items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 text-xs ring-inset';
  if (variant === 'selectable') {
    return (
      <button
        type="button"
        aria-pressed={selected}
        onClick={onToggle}
        className={`${base} ${selected ? 'bg-accent/10 ring-2 ring-accent' : 'bg-slate-800 ring-1 ring-slate-700 hover:bg-slate-700'} ${focusRing}`}
      >
        {inner}
      </button>
    );
  }
  return (
    <span className={`${base} bg-slate-800 ring-1 ring-slate-700`}>
      {inner}
      {variant === 'removable' && (
        <button
          type="button"
          onClick={onRemove}
          aria-label={`Remove ${tag.key}: ${tag.value}`}
          className={`-mr-1 ml-0.5 rounded-full p-0.5 text-fg-muted hover:bg-slate-700 hover:text-fg ${focusRing}`}
        >
          <Icon name="x" className="size-3" />
        </button>
      )}
    </span>
  );
}

// Up to `max` chips inline, then a "+N" chip opening a popover with the rest.
export function TagList({ tags, max = 3, className = '' }) {
  const { open, setOpen, ref } = usePopover();
  const popId = useId();
  if (!tags?.length) return null;
  const shown = tags.slice(0, max);
  const rest = tags.slice(max);
  return (
    <div className={`flex flex-wrap items-center gap-1.5 ${className}`}>
      {shown.map((t) => (
        <TagChip key={tagId(t)} tag={t} />
      ))}
      {rest.length > 0 && (
        <span ref={ref} className="relative">
          <button
            type="button"
            aria-expanded={open}
            aria-controls={popId}
            aria-label={`Show ${rest.length} more tags`}
            onClick={(e) => {
              e.stopPropagation();
              setOpen((o) => !o);
            }}
            className={`inline-flex h-7 items-center rounded-full bg-slate-800 px-2.5 text-xs font-medium text-slate-100 ring-1 ring-inset ring-slate-700 hover:bg-slate-700 ${focusRing}`}
          >
            +{rest.length}
          </button>
          {open && (
            <div id={popId} className="absolute left-0 top-full z-30 mt-2 flex w-max max-w-72 flex-wrap gap-1.5 rounded-xl border border-line bg-surface-raised p-3 shadow-panel">
              {rest.map((t) => (
                <TagChip key={tagId(t)} tag={t} />
              ))}
            </div>
          )}
        </span>
      )}
    </div>
  );
}

// Key combobox + value combobox + Add (UI/UX spec). Native <datalist> gives an
// accessible combobox with free typing. One value per key; re-adding a key
// replaces its value with a short inline note.
export function TagInput({ tags, onChange, index = [], idPrefix = 'tag', disabled = false }) {
  const uid = useId();
  const [key, setKey] = useState('');
  const [value, setValue] = useState('');
  const [note, setNote] = useState(null);
  const [error, setError] = useState(null);
  const valueRef = useRef(null);
  const keyRef = useRef(null);
  const keyList = `${uid}-keys`;
  const valueList = `${uid}-values`;
  const keys = keySuggestions(index);
  const values = valueSuggestions(index, key);
  const used = new Set(tags.map((t) => norm(t.key)));

  const add = () => {
    if (!key.trim()) {
      setError('Enter a tag name, like Weather.');
      keyRef.current?.focus();
      return;
    }
    if (key.includes(':')) {
      setError('Tag names can’t contain “:”.');
      keyRef.current?.focus();
      return;
    }
    if (!value.trim()) {
      setError(`Enter a value for ${key.trim()}.`);
      valueRef.current?.focus();
      return;
    }
    const tag = cleanTag({ key, value }, index);
    const { tags: next, replaced } = upsertTag(tags, tag);
    onChange(next);
    setError(null);
    setNote(replaced ? `Replaced ${replaced.key}: ${replaced.value} with ${tag.value} (one value per tag).` : `Added ${tag.key}: ${tag.value}.`);
    setKey('');
    setValue('');
    keyRef.current?.focus();
  };

  const quick = (k) => {
    setKey(k);
    setError(null);
    requestAnimationFrame(() => valueRef.current?.focus());
  };

  return (
    <div>
      {tags.length > 0 && (
        <ul aria-label="Tags on this match" className="mb-3 flex flex-wrap gap-1.5">
          {tags.map((t) => (
            <li key={tagId(t)}>
              <TagChip
                tag={t}
                variant={disabled ? 'static' : 'removable'}
                onRemove={() => {
                  onChange(removeTag(tags, t.key));
                  setNote(`Removed ${t.key}: ${t.value}.`);
                }}
              />
            </li>
          ))}
        </ul>
      )}
      <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
        <div>
          <label htmlFor={`${idPrefix}-key`} className="sr-only">
            Tag
          </label>
          <input
            id={`${idPrefix}-key`}
            ref={keyRef}
            list={keyList}
            value={key}
            disabled={disabled}
            maxLength={40}
            placeholder="Tag, e.g. Weather"
            autoComplete="off"
            onChange={(e) => {
              setKey(e.target.value);
              setError(null);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                valueRef.current?.focus();
              }
            }}
            aria-describedby={`${idPrefix}-help`}
            className={input}
          />
          <datalist id={keyList}>
            {keys.map((k) => (
              <option key={k} value={k} />
            ))}
          </datalist>
        </div>
        <div>
          <label htmlFor={`${idPrefix}-value`} className="sr-only">
            Value
          </label>
          <input
            id={`${idPrefix}-value`}
            ref={valueRef}
            list={valueList}
            value={value}
            disabled={disabled}
            maxLength={40}
            placeholder={key ? `${key.trim()} value` : 'Value, e.g. Raining'}
            autoComplete="off"
            onChange={(e) => {
              setValue(e.target.value);
              setError(null);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                add();
              }
            }}
            aria-describedby={`${idPrefix}-help`}
            className={input}
          />
          <datalist id={valueList}>
            {values.map((v) => (
              <option key={v} value={v} />
            ))}
          </datalist>
        </div>
        <button type="button" onClick={add} disabled={disabled} className={`${btn.secondary} h-11`}>
          <Icon name="plus" className="size-4" />
          Add
        </button>
      </div>
      <p id={`${idPrefix}-help`} className={`mt-2 text-caption ${error ? 'text-status-danger' : 'text-fg-muted'}`} aria-live="polite">
        {error || note || 'Pick a suggestion or type your own. One value per tag.'}
      </p>
      {!disabled && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {QUICK_ADD_KEYS.filter((k) => !used.has(norm(k))).map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => quick(k)}
              className={`inline-flex h-7 items-center gap-1 rounded-full border border-dashed border-line-strong px-2.5 text-xs text-fg-secondary hover:border-slate-500 hover:text-fg ${focusRing}`}
            >
              + {k}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
