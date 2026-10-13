// UI/UX spec stepper. Backend stages: queued, detect, track, ocr, metrics,
// ingest, done | failed. "ingest" is folded into Computing metrics.
export const STEPS = ['Uploaded', 'Detecting players', 'Tracking', 'Reading jersey numbers', 'Computing metrics', 'Done'];

// PROCESSING_STAGES index (detect 0 .. ingest 4) -> STEPS index.
const STAGE_TO_STEP = [1, 2, 3, 4, 4];

export function stepState({ phase, stageIdx, failedStep }) {
  if (phase === 'complete') return { current: 5, failedAt: null };
  if (phase === 'failed') return { current: -1, failedAt: STAGE_TO_STEP[failedStep ?? 0] ?? 1 };
  if (phase === 'queued' || stageIdx < 0) return { current: 1, failedAt: null, waiting: phase === 'queued' };
  return { current: STAGE_TO_STEP[stageIdx] ?? 1, failedAt: null };
}

export function stepLabel(progress) {
  const { current, failedAt, waiting } = stepState(progress);
  if (failedAt != null) return `Failed at ${STEPS[failedAt].toLowerCase()}`;
  if (current >= 5) return 'Done';
  if (waiting) return 'Queued';
  return STEPS[current];
}


// Time left from REAL observed throughput only: samples [{t, p}] collected from
// successive status polls. Needs >= 2 samples over >= 10 s with progress moving.
export function addEtaSample(samples, percent, now = Date.now()) {
  if (percent == null || !Number.isFinite(percent)) return { samples: [], eta: null };
  const list = samples.length && samples[samples.length - 1].p === percent ? samples : [...samples, { t: now, p: percent }].slice(-12);
  const a = list[0];
  const b = list[list.length - 1];
  const dt = (b.t - a.t) / 1000;
  const dp = b.p - a.p;
  return { samples: list, eta: list.length >= 2 && dt >= 10 && dp > 0 ? ((100 - b.p) / dp) * dt : null };
}
