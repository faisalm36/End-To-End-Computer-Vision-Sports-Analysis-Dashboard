import { useState } from 'react';
import { isUnsupported, updateVideoTags } from '../lib/api';
import { tagsOf } from '../lib/tags';
import { btn } from './classes';
import { TagInput, TagList } from './Tags';
import { Icon, Spinner } from './ui';

// Tags under the match title on /videos/:id. Ghost "Edit tags" turns them into
// the tag input inline; Save/Cancel at the right; Esc cancels.
export default function VideoTags({ video, index, demo = false, onSaved }) {
  const current = tagsOf(video);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(current);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const start = () => {
    setDraft(current);
    setError(null);
    setEditing(true);
    // Move focus into the editor so Esc (and keyboard users) land in it.
    requestAnimationFrame(() => document.getElementById('video-tag-key')?.focus());
  };
  const cancel = () => {
    setEditing(false);
    setError(null);
  };
  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      if (demo) {
        onSaved?.(draft);
      } else {
        const res = await updateVideoTags(video.id ?? video.video_id, draft);
        const saved = Array.isArray(res?.tags) ? res.tags : draft;
        onSaved?.(saved);
      }
      setEditing(false);
    } catch (err) {
      setError(
        isUnsupported(err)
          ? 'Tags can’t be saved yet: this server doesn’t have the tags endpoint. Your edits are still here.'
          : err?.message || 'Couldn’t save tags.',
      );
    } finally {
      setSaving(false);
    }
  };

  if (!editing) {
    return (
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {current.length ? <TagList tags={current} max={5} /> : <span className="text-caption text-fg-muted">No tags yet</span>}
        <button type="button" onClick={start} className={`${btn.ghost} h-8 px-2.5 text-caption`}>
          <Icon name="tag" className="size-3.5" />
          {current.length ? 'Edit tags' : 'Add tags'}
        </button>
      </div>
    );
  }
  return (
    <div
      className="mt-3 rounded-xl border border-slate-800 bg-slate-900/60 p-4"
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.stopPropagation();
          cancel();
        }
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-body font-medium text-fg">Edit match tags</p>
        <div className="flex gap-2">
          <button type="button" onClick={cancel} className={`${btn.ghost} h-9 px-3`}>
            Cancel
          </button>
          <button type="button" onClick={save} disabled={saving} className={`${btn.primary} h-9 px-4`}>
            {saving && <Spinner className="size-3.5" />}
            Save
          </button>
        </div>
      </div>
      <div className="mt-3">
        <TagInput tags={draft} onChange={setDraft} index={index} idPrefix="video-tag" />
      </div>
      {error && (
        <p role="alert" className="mt-2 text-caption text-status-danger">
          {error}
        </p>
      )}
    </div>
  );
}
