import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { useAuth } from '../auth/useAuth';
import { btn, card, container, focusRing, input, label } from '../components/classes';
import { Field, PasswordField } from '../components/FormField';
import { CompactProgress } from '../components/Progress';
import { TagChip, TagList } from '../components/Tags';
import { EmptyState, ErrorBanner, Icon, Modal, NoticeBanner, Skeleton, Spinner, StatusBadge } from '../components/ui';
import { changePassword, deleteVideo, listVideos, normalizeStatus, thumbnailSrc, updateMe, videoError, videoProgress } from '../lib/api';
import { indexFromVideos, matchesTagFilter, tagId, tagsOf } from '../lib/tags';
import { usePopover } from '../lib/usePopover';
import { displayName, formatDate, formatDuration, initials, matchOf, videoTitle } from '../lib/format';
import { SAMPLE_VIDEOS } from '../lib/sampleData';
import { MIN_PASSWORD } from '../lib/validation';

const PAGE_SIZE = 20;

// thumbnail_url is relative + self-tokened; rebuilt from API_BASE on every
// fetch. Falls back to the placeholder when missing or when the image errors.
function Thumb({ video }) {
  const src = thumbnailSrc(video);
  const [failedSrc, setFailedSrc] = useState(null);
  const showImg = src && failedSrc !== src;
  return (
    <span className="relative flex aspect-video w-20 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-surface-sunken ring-1 ring-inset ring-line">
      {showImg ? (
        <img src={src} alt="" loading="lazy" onError={() => setFailedSrc(src)} className="h-full w-full object-cover" />
      ) : (
        <Icon name="film" className="size-5 text-fg-muted" />
      )}
    </span>
  );
}

function StatCard({ title, value, sub, loading }) {
  return (
    <div className={`${card} p-5`}>
      <p className={label}>{title}</p>
      {loading ? (
        <Skeleton className="mt-3 h-9 w-20" />
      ) : (
        <p className="mt-3 font-mono text-kpi tabular-nums text-fg">{value}</p>
      )}
      {sub && <p className="mt-1 text-caption text-fg-muted">{sub}</p>}
    </div>
  );
}

// "Tags" filter button + popover: keys as sections, values as selectable chips
// with counts. Same key = OR, different keys = AND.
function TagFilter({ index, selected, onToggle }) {
  const { open, setOpen, ref } = usePopover();
  const isOn = (key, value) => selected.some((t) => tagId(t) === tagId({ key, value }));
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-controls="tag-filter-pop"
        onClick={() => setOpen((o) => !o)}
        className={`${btn.secondary} h-9 shrink-0 px-3`}
      >
        <Icon name="filter" className="size-4" />
        Tags
        {selected.length > 0 && <span className="rounded-full bg-accent/15 px-1.5 font-mono text-caption text-accent">{selected.length}</span>}
      </button>
      {open && (
        <div
          id="tag-filter-pop"
          role="dialog"
          aria-label="Filter by tags"
          className="absolute right-0 top-full z-30 mt-2 w-[min(22rem,calc(100vw-2rem))] rounded-xl border border-line bg-surface-raised p-4 shadow-panel"
        >
          {index.length === 0 ? (
            <p className="text-body text-fg-muted">No tags yet. Add tags to a match on its results page or when uploading.</p>
          ) : (
            <div className="max-h-80 space-y-4 overflow-y-auto">
              {index.map((g) => (
                <section key={g.key} aria-label={g.key}>
                  <p className={label}>{g.key}</p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {g.values.map((v) => (
                      <TagChip
                        key={v.value}
                        tag={{ key: g.key, value: v.value }}
                        variant="selectable"
                        selected={isOn(g.key, v.value)}
                        onToggle={() => onToggle({ key: g.key, value: v.value })}
                        count={v.count}
                        showIcon={false}
                      />
                    ))}
                  </div>
                </section>
              ))}
            </div>
          )}
          <p className="mt-4 border-t border-line pt-3 text-caption text-fg-muted">
            Values of the same tag match any of them; different tags must all match.
          </p>
        </div>
      )}
    </div>
  );
}

function EditProfileModal({ open, onClose, user, onSaved, isDemo }) {
  const [name, setName] = useState(displayName(user, { fallbackToEmail: false }));
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [errors, setErrors] = useState({});
  const [status, setStatus] = useState(null); // {type, text}
  const [saving, setSaving] = useState(false);

  const save = async (e) => {
    e.preventDefault();
    const errs = {
      name: name.trim() ? '' : 'Enter your name.',
      next: next && next.length < MIN_PASSWORD ? `Use at least ${MIN_PASSWORD} characters.` : '',
      current: next && !current ? 'Enter your current password.' : '',
    };
    setErrors(errs);
    if (Object.values(errs).some(Boolean)) return;
    if (isDemo) {
      setStatus({ type: 'error', text: 'Profile changes aren’t saved in demo mode.' });
      return;
    }
    setSaving(true);
    setStatus(null);
    const done = [];
    try {
      if (name.trim() !== displayName(user, { fallbackToEmail: false })) {
        const updated = await updateMe({ name: name.trim() });
        onSaved(updated?.user ?? updated ?? { name: name.trim() });
        done.push('Name updated.');
      }
    } catch (err) {
      setStatus({ type: 'error', text: `Couldn’t update your name: ${err?.message || 'please try again.'}` });
      setSaving(false);
      return;
    }
    if (next) {
      try {
        await changePassword(current, next); // 204
        setCurrent('');
        setNext('');
        done.push('Password changed.');
      } catch (err) {
        // 400 = wrong current password. It's not a 401, so the session stays.
        if (err?.status === 400) {
          setErrors((s) => ({ ...s, current: typeof err.data?.detail === 'string' ? err.data.detail : 'Current password is incorrect.' }));
        } else {
          setStatus({ type: 'error', text: `Couldn’t change your password: ${err?.message || 'please try again.'}` });
        }
        if (done.length) setStatus((st) => st || { type: 'ok', text: done.join(' ') });
        setSaving(false);
        return;
      }
    }
    setStatus({ type: 'ok', text: done.length ? done.join(' ') : 'Nothing to change.' });
    setSaving(false);
  };

  return (
    <Modal open={open} onClose={onClose} title="Account settings" labelledBy="edit-profile-title">
      <form noValidate onSubmit={save} className="space-y-4">
        {status && (
          <p role={status.type === 'error' ? 'alert' : 'status'} className={`text-body ${status.type === 'error' ? 'text-status-danger' : 'text-fg-secondary'}`}>
            {status.text}
          </p>
        )}
        <Field label="Name" name="name" value={name} onChange={(e) => setName(e.target.value)} onBlur={() => setErrors((s) => ({ ...s, name: name.trim() ? '' : 'Enter your name.' }))} error={errors.name} autoComplete="name" />
        <Field label="Email" value={user?.email || ''} readOnly disabled hint="Email can’t be changed here." />
        <fieldset className="space-y-4 border-t border-line pt-4">
          <legend className={`${label} pt-4`}>Change password</legend>
          <PasswordField label="Current password" name="current_password" value={current} onChange={(e) => setCurrent(e.target.value)} error={errors.current} autoComplete="current-password" />
          <PasswordField
            label="New password"
            name="new_password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            onBlur={() => setErrors((s) => ({ ...s, next: next && next.length < MIN_PASSWORD ? `Use at least ${MIN_PASSWORD} characters.` : '' }))}
            error={errors.next}
            hint="Leave blank to keep your current password."
            autoComplete="new-password"
          />
        </fieldset>
        <div className="flex justify-end gap-3 pt-2">
          <button type="button" onClick={onClose} className={btn.secondary}>
            Close
          </button>
          <button type="submit" disabled={saving} className={btn.primary}>
            {saving ? (
              <>
                <Spinner /> Saving…
              </>
            ) : (
              'Save changes'
            )}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export default function Profile() {
  const { user, isDemo, setUser } = useAuth();
  const navigate = useNavigate();

  const [videos, setVideos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [usingSample, setUsingSample] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [query, setQuery] = useState('');
  const [sortDir, setSortDir] = useState('desc');
  const [visible, setVisible] = useState(PAGE_SIZE);
  const [editing, setEditing] = useState(false);
  const [toDelete, setToDelete] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState(null);
  const [tagFilter, setTagFilter] = useState([]);
  // Server-side tag filter (GET /api/videos?tag=key:value). While it loads, or if the
  // backend doesn't support it, the same filter runs in the browser.
  const [serverFilter, setServerFilter] = useState(null); // { key, ids: Set } | null
  const filterKey = tagFilter.map(tagId).sort().join('|');

  useEffect(() => {
    if (!filterKey || usingSample || isDemo) return undefined;
    const controller = new AbortController();
    listVideos({ tags: tagFilter, signal: controller.signal })
      .then((list) => {
        // An older backend ignores ?tag= and returns everything: only trust the answer
        // when every returned video really carries the selected tags.
        if (list.every((v) => matchesTagFilter(v, tagFilter))) setServerFilter({ key: filterKey, ids: new Set(list.map((v) => String(v.id))) });
      })
      .catch(() => {}); // unsupported / network: keep the client-side filter
    return () => controller.abort();
  }, [tagFilter, filterKey, usingSample, isDemo, reloadKey]);
  const serverIds = serverFilter && serverFilter.key === filterKey ? serverFilter.ids : null;

  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      setLoading(true);
      setError(null);
      if (isDemo) {
        setVideos(SAMPLE_VIDEOS);
        setUsingSample(true);
        setLoading(false);
        return;
      }
      try {
        const list = await listVideos({ signal: controller.signal });
        setVideos(list);
        setUsingSample(false);
      } catch (err) {
        if (err?.kind === 'abort') return;
        setError(err);
        if (err?.isNetwork) {
          setVideos(SAMPLE_VIDEOS);
          setUsingSample(true);
        } else {
          setVideos([]);
          setUsingSample(false);
        }
      }
      if (!controller.signal.aborted) setLoading(false);
    })();
    return () => controller.abort();
  }, [isDemo, reloadKey]);

  const dateOf = (v) => v.uploaded_at || v.created_at || v.match_date || '';

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return videos
      .map((v) => ({ ...v, ...matchOf(v), _status: normalizeStatus(v.status), _title: videoTitle(v) }))
      .map((v) => ({ ...v, _tags: tagsOf(v) }))
      .filter((v) => !q || `${v._title} ${v.home_team || ''} ${v.away_team || ''}`.toLowerCase().includes(q))
      .filter((v) => (serverIds ? serverIds.has(String(v.id)) : matchesTagFilter(v, tagFilter)))
      .sort((a, b) => {
        const cmp = new Date(dateOf(a)).getTime() - new Date(dateOf(b)).getTime();
        return (sortDir === 'desc' ? -cmp : cmp) || 0;
      });
  }, [videos, query, sortDir, tagFilter, serverIds]);

  const tagIndex = useMemo(() => indexFromVideos(videos), [videos]);
  const toggleTag = (t) => {
    setVisible(PAGE_SIZE);
    setTagFilter((sel) => (sel.some((x) => tagId(x) === tagId(t)) ? sel.filter((x) => tagId(x) !== tagId(t)) : [...sel, t]));
  };
  const clearFilters = () => {
    setTagFilter([]);
    setQuery('');
  };
  const filtering = Boolean(query.trim()) || tagFilter.length > 0;

  const stats = useMemo(() => {
    const completed = videos.filter((v) => normalizeStatus(v.status) === 'complete').length;
    const latest = [...videos].sort((a, b) => new Date(dateOf(b)) - new Date(dateOf(a)))[0];
    return { total: videos.length, completed, last: latest ? formatDate(dateOf(latest)) : '—' };
  }, [videos]);

  const confirmDelete = useCallback(async () => {
    if (!toDelete) return;
    if (usingSample) {
      setVideos((vs) => vs.filter((v) => v.id !== toDelete.id));
      setToDelete(null);
      return;
    }
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteVideo(toDelete.id);
      setVideos((vs) => vs.filter((v) => v.id !== toDelete.id));
      setToDelete(null);
    } catch (err) {
      setDeleteError(err?.message || 'Could not delete this video.');
    } finally {
      setDeleting(false);
    }
  }, [toDelete, usingSample]);

  const open = (v) => navigate(`/videos/${encodeURIComponent(v.id)}`);
  const shownName = displayName(user) || 'Your profile';
  const shown = rows.slice(0, visible);

  return (
    <div className={`${container} space-y-6 py-10 sm:py-12`}>
      <h1 className="sr-only">Profile and upload history</h1>

      {/* Header card */}
      <section className={`${card} flex flex-col gap-5 p-6 sm:flex-row sm:items-center sm:justify-between`}>
        <div className="flex items-center gap-4">
          <span className="flex size-16 shrink-0 items-center justify-center rounded-full bg-surface-overlay text-xl font-semibold text-fg ring-1 ring-line-strong">
            {initials(displayName(user) || user?.email)}
          </span>
          <div className="min-w-0">
            <p className="truncate text-headline text-fg">{shownName}</p>
            <p className="truncate text-body text-fg-secondary">{user?.email || 'Email unavailable'}</p>
            <p className="mt-0.5 text-caption text-fg-muted">
              Member since {user?.created_at ? formatDate(user.created_at) : '—'}
            </p>
          </div>
        </div>
        <button type="button" onClick={() => setEditing(true)} className={btn.secondary}>
          Edit profile
        </button>
      </section>

      {usingSample && (
        <NoticeBanner
          action={
            !isDemo && (
              <button type="button" onClick={() => setReloadKey((k) => k + 1)} className={`${btn.secondary} h-9 shrink-0`}>
                Retry
              </button>
            )
          }
        >
          {isDemo ? 'Demo mode: showing sample data.' : 'Backend not reachable, showing sample data.'}
        </NoticeBanner>
      )}

      {error && !usingSample && (
        <ErrorBanner title="Couldn’t load your uploads" onRetry={() => setReloadKey((k) => k + 1)}>
          {error.message}
        </ErrorBanner>
      )}

      {/* Stats */}
      <section aria-label="Upload summary" className="grid gap-4 sm:grid-cols-3">
        <StatCard title="Videos uploaded" value={stats.total} loading={loading} />
        <StatCard title="Matches analyzed" value={stats.completed} loading={loading} />
        <StatCard title="Last upload" value={<span className="text-2xl">{stats.last}</span>} loading={loading} />
      </section>

      {/* History */}
      <section aria-labelledby="history-title" className={`${card} overflow-hidden`} aria-busy={loading}>
        <div className="flex flex-col gap-3 border-b border-line px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
          <h2 id="history-title" className="text-title text-fg">
            Upload history
          </h2>
          <div className="flex gap-2">
            <label className="relative block w-full min-w-0 sm:w-64">
              <span className="sr-only">Search uploads by name</span>
              <Icon name="search" className="pointer-events-none absolute inset-y-0 left-3 my-auto size-4 text-fg-muted" />
              <input
                type="search"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setVisible(PAGE_SIZE);
                }}
                placeholder="Search by name"
                className={`${input} h-9 pl-9`}
              />
            </label>
            <TagFilter index={tagIndex} selected={tagFilter} onToggle={toggleTag} />
            <Link to="/upload" aria-label="Upload a match" className={`${btn.primary} h-9 shrink-0`}>
              <Icon name="upload" className="size-4" />
              <span className="hidden sm:inline">Upload</span>
            </Link>
          </div>
        </div>

        {(tagFilter.length > 0 || (filtering && !loading)) && (
          <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3 sm:px-5">
            {tagFilter.map((t) => (
              <TagChip key={tagId(t)} tag={t} variant="removable" onRemove={() => toggleTag(t)} />
            ))}
            {filtering && (
              <button type="button" onClick={clearFilters} className={`rounded text-caption font-medium text-fg underline underline-offset-4 ${focusRing}`}>
                Clear all
              </button>
            )}
            <p className="ml-auto text-caption text-fg-muted" data-filter-source={serverIds ? 'server' : 'client'}>
              Showing {rows.length} of {videos.length}
            </p>
          </div>
        )}

        {loading ? (
          <div className="space-y-3 p-5">
            {[0, 1, 2].map((i) => (
              <div key={i} className="flex items-center gap-4">
                <Skeleton className="h-11 w-20" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-3 w-1/3" />
                  <Skeleton className="h-3 w-1/5" />
                </div>
              </div>
            ))}
            <p className="text-caption text-fg-muted">Loading your uploads…</p>
          </div>
        ) : videos.length === 0 && !error ? (
          <div className="p-5">
            <EmptyState
              icon="video"
              title="No uploads yet"
              hint="Upload a match video to see speed, distance and a workload indicator for every player."
              action={
                <Link to="/upload" className={btn.primary}>
                  Upload your first match
                </Link>
              }
            />
          </div>
        ) : rows.length === 0 ? (
          <p className="px-5 py-12 text-center text-body text-fg-muted">
            {videos.length ? 'No uploads match your filters.' : 'Nothing to show.'}{' '}
            {filtering && (
              <button type="button" onClick={clearFilters} className={`rounded font-medium text-fg underline underline-offset-4 ${focusRing}`}>
                Clear filters
              </button>
            )}
          </p>
        ) : (
          <>
            {/* Table (lg+; stacked cards at 768 and below) */}
            <div className="hidden overflow-x-auto lg:block">
              <table className="min-w-full">
                <thead className="border-b border-line bg-surface-sunken">
                  <tr>
                    <th scope="col" className="px-4 py-2.5 text-left text-label uppercase text-fg-muted">Video / match</th>
                    <th scope="col" className="px-4 py-2.5 text-left text-label uppercase text-fg-muted" aria-sort={sortDir === 'desc' ? 'descending' : 'ascending'}>
                      <button type="button" onClick={() => setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))} className={`inline-flex items-center gap-1 rounded uppercase hover:text-fg ${focusRing}`}>
                        Date uploaded <span aria-hidden="true">{sortDir === 'desc' ? '▼' : '▲'}</span>
                      </button>
                    </th>
                    <th scope="col" className="px-4 py-2.5 text-left text-label uppercase text-fg-muted">Tags</th>
                    <th scope="col" className="px-4 py-2.5 text-right text-label uppercase text-fg-muted">Duration</th>
                    <th scope="col" className="px-4 py-2.5 text-left text-label uppercase text-fg-muted">Status</th>
                    <th scope="col" className="px-4 py-2.5 text-right text-label uppercase text-fg-muted">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((v) => (
                    <tr key={v.id} className="border-b border-line text-body text-fg-secondary transition-colors last:border-0 hover:bg-surface-overlay">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          <Thumb video={v} />
                          <div className="min-w-0">
                            <Link to={`/videos/${encodeURIComponent(v.id)}`} className={`block truncate rounded font-medium text-fg hover:underline ${focusRing}`}>
                              {v._title}
                            </Link>
                            <p className="truncate text-caption text-fg-muted">
                              {v.home_team && v.away_team ? `${v.home_team} vs ${v.away_team}` : 'Teams not set'}
                              {v.match_date ? ` · played ${formatDate(v.match_date)}` : ''}
                            </p>
                          </div>
                        </div>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">{formatDate(dateOf(v))}</td>
                      <td className="px-4 py-3">
                        {v._tags.length ? <TagList tags={v._tags} max={2} /> : <span className="text-caption text-fg-muted">—</span>}
                      </td>
                      <td className="px-4 py-3 text-right font-mono tabular-nums text-fg">{formatDuration(v.duration_seconds ?? v.duration)}</td>
                      <td className="px-4 py-3">
                        {v._status === 'processing' ? <CompactProgress progress={videoProgress(v)} /> : <StatusBadge status={v._status} />}
                        {v._status === 'failed' && videoError(v) && (
                          <p className="mt-1 max-w-56 truncate text-caption text-fg-muted" title={videoError(v)}>
                            {videoError(v)}
                          </p>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-2">
                          <button type="button" onClick={() => open(v)} className={`${btn.secondary} h-8 px-3 text-caption`}>
                            View results
                          </button>
                          <button type="button" onClick={() => setToDelete(v)} aria-label={`Delete ${v._title}`} className={`${btn.ghost} h-8 px-2`}>
                            <Icon name="trash" className="size-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Stacked cards (< lg) */}
            <ul className="divide-y divide-line lg:hidden">
              {shown.map((v) => (
                <li key={v.id} className="p-4">
                  <div className="flex items-start gap-3">
                    <Thumb video={v} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium text-fg">{v._title}</p>
                      <p className="mt-0.5 text-caption text-fg-muted">
                        {formatDate(dateOf(v))} · <span className="font-mono tabular-nums">{formatDuration(v.duration_seconds ?? v.duration)}</span>
                      </p>
                      <div className="mt-2">
                        {v._status === 'processing' ? <CompactProgress progress={videoProgress(v)} /> : <StatusBadge status={v._status} />}
                      </div>
                      {v._tags.length > 0 && <TagList tags={v._tags} max={3} className="mt-2" />}
                      {v._status === 'failed' && videoError(v) && <p className="mt-1 text-caption text-fg-muted">{videoError(v)}</p>}
                    </div>
                  </div>
                  <div className="mt-3 flex gap-2">
                    <button type="button" onClick={() => open(v)} className={`${btn.secondary} h-9 flex-1`}>
                      View results
                    </button>
                    <button type="button" onClick={() => setToDelete(v)} aria-label={`Delete ${v._title}`} className={`${btn.ghost} h-9 px-3`}>
                      <Icon name="trash" className="size-4" />
                    </button>
                  </div>
                </li>
              ))}
            </ul>

            <div className="flex items-center justify-between gap-4 border-t border-line px-4 py-3 sm:px-5">
              <p className="text-caption text-fg-muted">
                {/* The filter bar already says "Showing X of Y" while filtering; here it's paging only. */}
                {filtering ? `${shown.length} of ${rows.length} matching uploads listed` : `Showing ${shown.length} of ${rows.length}`}
              </p>
              {rows.length > visible && (
                <button type="button" onClick={() => setVisible((n) => n + PAGE_SIZE)} className={`${btn.secondary} h-9`}>
                  Load more
                </button>
              )}
            </div>
          </>
        )}
      </section>

      <EditProfileModal
        key={editing ? 'open' : 'closed'}
        open={editing}
        onClose={() => setEditing(false)}
        user={user}
        isDemo={isDemo}
        onSaved={(u) => setUser((prev) => ({ ...prev, ...u }))}
      />

      <Modal open={Boolean(toDelete)} onClose={() => { setToDelete(null); setDeleteError(null); }} title="Delete this video?" labelledBy="delete-title">
        <p className="text-body text-fg-secondary">
          “{toDelete ? videoTitle(toDelete) : ''}” and its results will be permanently removed. This can’t be undone.
        </p>
        {deleteError && (
          <p role="alert" className="mt-3 text-body text-status-danger">
            {deleteError}
          </p>
        )}
        <div className="mt-6 flex justify-end gap-3">
          <button type="button" onClick={() => { setToDelete(null); setDeleteError(null); }} className={btn.secondary}>
            Cancel
          </button>
          <button type="button" onClick={confirmDelete} disabled={deleting} className={btn.danger}>
            {deleting ? <Spinner /> : <Icon name="trash" className="size-4" />}
            Delete
          </button>
        </div>
      </Modal>
    </div>
  );
}
