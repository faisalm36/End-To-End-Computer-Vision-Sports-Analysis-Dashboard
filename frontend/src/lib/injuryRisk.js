// Roster injury-risk (model rir-1.0, backend v0.9.0) API calls, hooks and constants.
// Screening/education index only, not medical advice.
import { useCallback, useEffect, useState } from 'react';
import { request } from './api';

export const INJURY_DISCLAIMER =
  'Not medical advice. This injury-risk score is a screening and education index, not a diagnosis. Return-to-play and selection decisions belong to qualified medical staff.';

export const BAND_META = {
  low: { label: 'Low', icon: 'check', cls: 'bg-risk-low-bg text-risk-low ring-risk-low-ring', bar: 'bg-risk-low', dot: '#6ee7b7' },
  moderate: { label: 'Moderate', icon: 'alert', cls: 'bg-risk-medium-bg text-risk-medium ring-risk-medium-ring', bar: 'bg-risk-medium', dot: '#fcd34d' },
  high: { label: 'High', icon: 'alert', cls: 'bg-risk-high-bg text-risk-high ring-risk-high-ring', bar: 'bg-risk-high', dot: '#fda4af' },
};

export const BODY_PARTS = ['hamstring', 'groin', 'quadriceps', 'calf', 'ankle', 'knee', 'foot', 'hip', 'back', 'shoulder', 'head', 'other'];
export const INJURY_TYPES = ['muscle_strain', 'ligament_sprain', 'tendon', 'fracture', 'contusion', 'concussion', 'overuse', 'other'];
export const SIDES = ['na', 'left', 'right', 'both'];
export const SURFACES = ['unknown', 'grass', 'turf', 'hybrid', 'indoor'];
export const SURFACE_LABELS = { unknown: 'Not set', grass: 'Natural grass', turf: 'Artificial turf', hybrid: 'Hybrid grass', indoor: 'Indoor' };
export const pretty = (s) => (s === 'na' ? 'N/A' : String(s ?? '').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()));

const q = (params) => {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => v != null && v !== '' && sp.set(k, v));
  const s = sp.toString();
  return s ? `?${s}` : '';
};
const pid = (id) => encodeURIComponent(id);

export const getRosterInjuryRisk = ({ team_id, next_surface, next_date, sort = 'desc', signal } = {}) =>
  request(`/api/roster/injury-risk${q({ team_id, next_surface, next_date, sort })}`, { signal });
export const getPlayerInjuryRisk = (id, { next_surface, next_date, signal } = {}) =>
  request(`/api/players/${pid(id)}/injury-risk${q({ next_surface, next_date })}`, { signal });
export const listInjuries = (id, opts) => request(`/api/players/${pid(id)}/injuries`, opts);
export const createInjury = (id, body) => request(`/api/players/${pid(id)}/injuries`, { method: 'POST', body });
export const updateInjury = (id, injuryId, body) =>
  request(`/api/players/${pid(id)}/injuries/${pid(injuryId)}`, { method: 'PATCH', body });
export const deleteInjury = (id, injuryId) => request(`/api/players/${pid(id)}/injuries/${pid(injuryId)}`, { method: 'DELETE' });

// Generic loader hook: re-runs when deps change; reload() forces a refetch.
export function useLoader(fn, deps) {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [tick, setTick] = useState(0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const load = useCallback(fn, deps);
  useEffect(() => {
    const ctrl = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    load(ctrl.signal)
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((error) => error?.kind !== 'abort' && !ctrl.signal.aborted && setState({ loading: false, data: null, error }));
    return () => ctrl.abort();
  }, [load, tick]);
  return { ...state, reload: () => setTick((t) => t + 1) };
}

export const useRosterInjuryRisk = (p) =>
  useLoader((signal) => getRosterInjuryRisk({ ...p, signal }), [p.team_id, p.next_surface, p.next_date, p.sort]);
export const usePlayerInjuryRisk = (id, p) =>
  useLoader((signal) => getPlayerInjuryRisk(id, { ...p, signal }), [id, p.next_surface, p.next_date]);
export const useInjuries = (id) => useLoader((signal) => listInjuries(id, { signal }), [id]);
