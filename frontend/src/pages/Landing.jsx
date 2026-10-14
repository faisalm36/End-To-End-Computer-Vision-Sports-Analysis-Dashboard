import { Link } from 'react-router';
import { useAuth } from '../auth/useAuth';
import { btn, card, container, focusRing, label } from '../components/classes';
import { Icon } from '../components/ui';
import { METRIC_GROUPS, statusFromRegistry, thresholdText, WORKLOAD_DISCLAIMER } from '../lib/metrics';
import { useMetricDefs } from '../lib/useMetricDefs';

const FEATURES = [
  {
    icon: 'target',
    title: 'Player tracking with YOLO',
    body: 'Computer vision finds every player in every frame and follows them across the pitch, then maps each position onto real pitch metres.',
  },
  {
    icon: 'hash',
    title: 'Jersey ID with OCR',
    body: 'Jersey numbers are read straight from the footage, so each track is tied to a real player instead of an anonymous dot.',
  },
  {
    icon: 'gauge',
    title: 'Speed, distance & workload',
    body: 'Distance, max sustained speed and distance per minute for every player, plus a workload indicator to help plan the next session.',
  },
];

const STEPS = [
  { title: 'Upload', body: 'Record the match on a phone or any camera you already own, then drop the mp4 or mov file in.' },
  { title: 'Process', body: 'We detect and track players, read jersey numbers and compute each player’s metrics for you.' },
  { title: 'Analyze', body: 'Open the dashboard to compare players, see who carried the heaviest load and plan the next session.' },
];

// Static, clearly labelled illustration of the dashboard KPI cards.
function HeroMock() {
  const rows = [
    { name: 'Player #9', speed: 22.0, dist: 4.9 },
    { name: 'Player #7', speed: 21.4, dist: 5.8 },
    { name: 'Player #14', speed: 20.7, dist: 7.0 },
  ];
  return (
    <figure className="relative">
      <div className="rounded-card bg-surface-raised p-4 shadow-panel ring-1 ring-line sm:p-5">
        <div className="flex items-center justify-between">
          <p className={label}>Match overview</p>
          <span className="rounded-chip bg-surface-overlay px-2.5 py-0.5 text-caption text-fg-muted ring-1 ring-inset ring-line-strong">
            Illustrative sample
          </span>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3">
          <div className="rounded-xl bg-surface-sunken p-4 ring-1 ring-inset ring-line">
            <p className={`${label} flex items-center gap-2`}>
              <span className="size-2 rounded-full bg-metric-speed" />
              Top speed
            </p>
            <p className="mt-2 flex items-baseline gap-1">
              <span className="font-mono text-kpi tabular-nums text-fg">22.0</span>
              <span className="text-body text-fg-muted">mph</span>
            </p>
          </div>
          <div className="rounded-xl bg-surface-sunken p-4 ring-1 ring-inset ring-line">
            <p className={`${label} flex items-center gap-2`}>
              <span className="size-2 rounded-full bg-metric-distance" />
              Distance
            </p>
            <p className="mt-2 flex items-baseline gap-1">
              <span className="font-mono text-kpi tabular-nums text-fg">7.0</span>
              <span className="text-body text-fg-muted">km</span>
            </p>
          </div>
        </div>
        <ul className="mt-4 space-y-3">
          {rows.map((r) => (
            <li key={r.name} className="grid grid-cols-[5.5rem_1fr_1fr] items-center gap-3">
              <span className="truncate text-caption text-fg-secondary">{r.name}</span>
              <span className="h-2 overflow-hidden rounded-full bg-surface-sunken ring-1 ring-inset ring-line">
                <span className="block h-full rounded-full bg-metric-speed" style={{ width: `${(r.speed / 22) * 100}%` }} />
              </span>
              <span className="h-2 overflow-hidden rounded-full bg-surface-sunken ring-1 ring-inset ring-line">
                <span className="block h-full rounded-full bg-metric-distance" style={{ width: `${(r.dist / 7) * 100}%` }} />
              </span>
            </li>
          ))}
        </ul>
        <div className="mt-4 flex gap-4 text-caption text-fg-muted">
          <span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-metric-speed" />Speed</span>
          <span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-metric-distance" />Distance</span>
        </div>
      </div>
      <figcaption className="sr-only">Illustration of the analytics dashboard with sample values</figcaption>
    </figure>
  );
}

const DOT = {
  speed: 'bg-metric-speed',
  distance: 'bg-metric-distance',
};

const ACCURACY = [
  { title: 'Calibrated to the pitch', body: 'Pitch lines map every frame to real metres, so distances and speeds come from the field, not from pixels.' },
  { title: 'Max sustained speed', body: 'Speed is smoothed and must be held for about a second, so one jumpy frame can’t pass for a record sprint.' },
  { title: 'Labelled as estimates', body: 'Physical stats carry an “Estimated from video” badge, and sprint metrics show the speed thresholds they use.' },
  { title: 'You can fix the numbers', body: 'Shirt numbers are read automatically, and you can correct a misread number so stats land on the right player.' },
];

const BADGE = {
  next: { text: 'Coming soon', cls: 'border border-dashed border-line-strong text-fg-secondary' },
  manual: { text: 'Tagged by you', cls: 'bg-surface-overlay text-fg-secondary ring-1 ring-inset ring-line-strong' },
};

function StatusBadge({ status }) {
  const b = BADGE[status];
  if (!b) return null;
  return <span className={`shrink-0 rounded-chip px-2 py-0.5 text-caption font-medium ${b.cls}`}>{b.text}</span>;
}

function MetricGroup({ group }) {
  const counts = { launch: 0, next: 0, manual: 0 };
  group.metrics.forEach((m) => (counts[m.status] += 1));
  const summary = [
    counts.launch && `${counts.launch} tracked`,
    counts.next && `${counts.next} coming soon`,
    counts.manual && `${counts.manual} tagged by you`,
  ]
    .filter(Boolean)
    .join(' · ');
  const hasThresholds = group.metrics.some((m) => m.thresholds);
  return (
    <article aria-labelledby={`grp-${group.id}`} className={`${card} flex flex-col p-6`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id={`grp-${group.id}`} className="text-title text-fg">{group.title}</h3>
        <span className="text-caption text-fg-muted">{summary}</span>
      </div>
      <p className="mt-1 text-body text-fg-muted">{group.blurb}</p>
      <ul className="mt-5 divide-y divide-line">
        {group.metrics.map((m) => (
          <li key={m.id} className="flex gap-3 py-3 first:pt-0 last:pb-0">
            <span aria-hidden="true" className={`mt-2 size-2 shrink-0 rounded-full ${DOT[m.metric] || 'bg-fg-muted'}`} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="text-body font-semibold text-fg">{m.name}</span>
                <span className="font-mono text-caption text-fg-muted">{m.unit}</span>
                <StatusBadge status={m.status} />
              </div>
              <p className="mt-0.5 text-body text-fg-secondary">{m.desc}</p>
            </div>
          </li>
        ))}
      </ul>
      {hasThresholds && <p className="mt-4 font-mono text-caption text-fg-muted">Speed thresholds: {thresholdText()}</p>}
    </article>
  );
}

function WhatWeTrack() {
  // Tracked vs Coming soon follows the backend's /api/metrics registry (falls back to lib/metrics.js).
  const { availability } = useMetricDefs();
  const groups = METRIC_GROUPS.map((g) => ({ ...g, metrics: g.metrics.map((m) => ({ ...m, status: statusFromRegistry(m, availability) })) }));
  return (
    <section id="what-we-track" aria-labelledby="track" className="scroll-mt-20 border-b border-line">
      <div className={`${container} py-20 sm:py-24`}>
        <div className="max-w-3xl">
          <p className={label}>What we track</p>
          <h2 id="track" className="mt-3 text-3xl font-bold tracking-tight text-fg sm:text-4xl">
            The numbers coaches and players actually use.
          </h2>
          <p className="mt-5 text-lg text-fg-secondary">
            Every uploaded match gives you the physical and positional numbers pro clubs rely on, estimated from player tracking mapped onto the real pitch. Intensity metrics arrive next, and match events come from your own tags, never from AI guesswork.
          </p>
        </div>

        <div className="mt-12 grid gap-4 lg:grid-cols-2">
          <div className="lg:row-span-2">
            <MetricGroup group={groups[0]} />
          </div>
          {groups.slice(1).map((g) => (
            <MetricGroup key={g.id} group={g} />
          ))}
        </div>

        <div className={`${card} mt-4 flex flex-col gap-3 p-6 sm:flex-row sm:items-start sm:gap-6`}>
          <p className={`${label} shrink-0 sm:w-40 sm:pt-1`}>Workload indicator</p>
          <p className="text-body text-fg-secondary">
            A Low / Medium / High workload flag per player, built from the match’s physical load to help you plan training and recovery.{' '}
            <span className="font-semibold text-fg">{WORKLOAD_DISCLAIMER}.</span>
          </p>
        </div>

        <div className="mt-16">
          <h3 className="text-2xl font-bold tracking-tight text-fg">Built for accuracy.</h3>
          <p className="mt-2 max-w-2xl text-body text-fg-muted">
            Video tracking is only as good as the footage behind it. Here’s how we keep the numbers honest.
          </p>
          <ul className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {ACCURACY.map((a) => (
              <li key={a.title} className="flex gap-3">
                <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-surface-overlay text-fg ring-1 ring-inset ring-line-strong">
                  <Icon name="check" className="size-4" />
                </span>
                <div>
                  <p className="text-body font-semibold text-fg">{a.title}</p>
                  <p className="mt-1 text-body text-fg-secondary">{a.body}</p>
                </div>
              </li>
            ))}
          </ul>
          <p className="mt-8 max-w-3xl text-caption text-fg-muted">
            Best results come from one fixed, elevated camera that sees the whole pitch (1080p, 25 fps or more). Panning or follow-cam footage makes the numbers unreliable. We’ll publish accuracy figures only once we’ve measured them against ground truth.
          </p>
        </div>
      </div>
    </section>
  );
}

export default function Landing() {
  const { isAuthenticated } = useAuth();
  const uploadHref = isAuthenticated ? '/upload' : '/signup';

  return (
    <div>
      {/* Hero */}
      <section className="relative overflow-hidden border-b border-line">
        <div aria-hidden="true" className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_50%_at_20%_0%,rgb(148_163_184/0.10),transparent)]" />
        <div className={`${container} relative grid items-center gap-12 py-20 sm:py-24 lg:grid-cols-2`}>
          <div>
            <p className={label}>Soccer video analytics</p>
            <h1 className="mt-4 text-5xl font-bold tracking-tight text-fg sm:text-6xl">
              Every sprint, every metre, from match video.
            </h1>
            <p className="mt-6 max-w-xl text-lg text-fg-muted">
              Film the match on your phone. We track every player to estimate distance, top speed, work rate and heat maps, plus a workload indicator. No cameras or GPS vests to buy.
            </p>
            <div className="mt-8 flex flex-col gap-3 sm:flex-row">
              <Link to={uploadHref} className={`${btn.primary} h-12 px-6 text-base shadow-accent-glow`}>
                Upload a match
                <Icon name="arrowRight" className="size-4" />
              </Link>
              <Link to="/dashboard" className={`${btn.secondary} h-12 px-6 text-base`}>
                See the dashboard
              </Link>
            </div>
            <a href="#what-we-track" className={`mt-6 inline-flex items-center gap-1.5 rounded text-body text-fg-secondary hover:text-fg ${focusRing}`}>
              See exactly what we track
              <Icon name="arrowRight" className="size-4" />
            </a>
          </div>
          <HeroMock />
        </div>

      </section>

      <WhatWeTrack />

      {/* Who we are */}
      <section aria-labelledby="who" className={`${container} py-20 sm:py-24`}>
        <div className="max-w-3xl">
          <p className={label}>Who we are</p>
          <h2 id="who" className="mt-3 text-3xl font-bold tracking-tight text-fg sm:text-4xl">
            Built by a player, for the people who love the game.
          </h2>
          <p className="mt-5 text-lg text-fg-secondary">
            {'We started as a capstone project with a simple question: why should match analytics belong only to professional clubs? '}
            {'We combine computer vision, jersey-number recognition and sports science into one tool that anyone with a match video can use.'}
          </p>
        </div>
      </section>

      {/* What we do */}
      <section aria-labelledby="what" className="border-y border-line bg-surface-raised/40">
        <div className={`${container} py-20 sm:py-24`}>
          <p className={label}>What we do</p>
          <h2 id="what" className="mt-3 max-w-2xl text-3xl font-bold tracking-tight text-fg sm:text-4xl">
            From raw footage to a clear picture of every player.
          </h2>
          <div className="mt-12 grid gap-4 md:grid-cols-3">
            {FEATURES.map((f) => (
              <article key={f.title} className={`${card} p-6`}>
                <span className="flex size-11 items-center justify-center rounded-xl bg-surface-overlay text-fg ring-1 ring-inset ring-line-strong">
                  <Icon name={f.icon} className="size-5" />
                </span>
                <h3 className="mt-5 text-title text-fg">{f.title}</h3>
                <p className="mt-2 text-body text-fg-secondary">{f.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section aria-labelledby="how" className={`${container} py-20 sm:py-24`}>
        <p className={label}>How it works</p>
        <h2 id="how" className="mt-3 text-3xl font-bold tracking-tight text-fg sm:text-4xl">
          Three steps. No hardware.
        </h2>
        <ol className="mt-12 grid gap-4 md:grid-cols-3">
          {STEPS.map((s, i) => (
            <li key={s.title} className={`${card} relative p-6`}>
              <span className="flex size-9 items-center justify-center rounded-full bg-surface-overlay font-mono text-body font-semibold tabular-nums text-fg ring-1 ring-inset ring-line-strong">
                {i + 1}
              </span>
              <h3 className="mt-4 text-title text-fg">{s.title}</h3>
              <p className="mt-2 text-body text-fg-secondary">{s.body}</p>
            </li>
          ))}
        </ol>
      </section>

      {/* Mission + Why */}
      <section aria-labelledby="mission" className="border-y border-line bg-surface-raised/40">
        <div className={`${container} grid gap-12 py-20 sm:py-24 lg:grid-cols-2`}>
          <div>
            <p className={label}>Our mission</p>
            <h2 id="mission" className="mt-3 text-3xl font-bold tracking-tight text-fg sm:text-4xl">
              Pro-level insight for every pitch.
            </h2>
            <p className="mt-5 text-lg text-fg-secondary">
              Our mission is to put professional-grade match analysis in the hands of every amateur and youth player and coach, using footage they already have.
            </p>
            <p className="mt-6 text-sm font-semibold uppercase tracking-label text-fg-muted">Our why</p>
            <p className="mt-3 text-lg text-fg-secondary">
              Top clubs have analysts, tracking systems and budgets. Most teams have a parent with a phone on the touchline. We think that footage deserves the same attention, so every player can see how hard they worked, every coach can manage workload with evidence, and nobody has to guess.
            </p>
          </div>
          <blockquote className="flex items-center">
            <div className="border-l-4 border-line-strong pl-6">
              <p className="text-2xl font-semibold leading-snug tracking-tight text-fg sm:text-3xl">
                “You shouldn’t need a pro club’s budget to understand your own game. A phone video should be enough.”
              </p>
              <footer className="mt-4 text-body text-fg-muted">Our founding belief</footer>
            </div>
          </blockquote>
        </div>
      </section>

      {/* Final CTA */}
      <section className={`${container} py-20 sm:py-24`}>
        <div className={`${card} flex flex-col items-start gap-6 p-8 sm:p-10 lg:flex-row lg:items-center lg:justify-between`}>
          <div>
            <h2 className="text-2xl font-bold tracking-tight text-fg sm:text-3xl">See your next match through AI.</h2>
            <p className="mt-2 text-body text-fg-muted">Create an account and upload your first match video today.</p>
          </div>
          <div className="flex w-full flex-col gap-3 sm:w-auto sm:flex-row">
            <Link to={isAuthenticated ? '/upload' : '/signup'} className={`${btn.primary} h-12 px-6 text-base`}>
              {isAuthenticated ? 'Upload a match' : 'Create your account'}
            </Link>
            {!isAuthenticated && (
              <Link to="/login" className={`${btn.secondary} h-12 px-6 text-base`}>
                Log in
              </Link>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
