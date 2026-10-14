// Clearly-labelled sample data used only when the backend is not reachable
// (or in demo mode). Shapes match the API contract the backend should return.

export const SAMPLE_PLAYERS = [
  { player_id: 21, name: 'Faisal Musa', top_speed_mph: 19.2, distance_km: 4.5, distance_covered_meters: 4500, top_speed_kmh: 30.9, injury_risk: 'Low', fatigue_risk_score: 0, minutes_played: 90, sprint_count: 12 },
  { player_id: 7, name: 'Luka Petrovic', top_speed_mph: 21.4, distance_km: 5.8, distance_covered_meters: 5800, top_speed_kmh: 34.4, injury_risk: 'Medium', fatigue_risk_score: 50, minutes_played: 88, sprint_count: 18 },
  { player_id: 10, name: 'Marco Silva', top_speed_mph: 20.1, distance_km: 6.3, distance_covered_meters: 6300, top_speed_kmh: 32.3, injury_risk: 'High', fatigue_risk_score: 100, minutes_played: 92, sprint_count: 15 },
  { player_id: 4, name: 'Tomas Novak', top_speed_mph: 17.8, distance_km: 5.1, injury_risk: 'Low' },
  { player_id: 9, name: 'Andrej Kovac', top_speed_mph: 22.0, distance_km: 4.9, injury_risk: 'Medium' },
  { player_id: 1, name: 'Ivan Horvat', top_speed_mph: 14.6, distance_km: 2.3, injury_risk: 'Low' },
  { player_id: 14, name: 'Jan Dvorak', top_speed_mph: 20.7, distance_km: 7.0, injury_risk: 'High' },
  { player_id: 8, name: 'Mateo Rossi', top_speed_mph: 18.9, distance_km: 6.1, injury_risk: 'Low' },
];

export const SAMPLE_VIDEOS = [
  {
    id: 'sample-3',
    title: 'Sunday league vs Riverside',
    match_date: '2026-09-27',
    home_team: 'Northside FC',
    away_team: 'Riverside',
    status: 'processing',
    stage: 'track',
    progress: 38,
    created_at: '2026-09-28T14:10:00Z',
    duration_seconds: 5412,
    video_type: 'tactical_cam',
    resolution: '1920x1080',
    thumbnail_url: null,
    tags: [
      { key: 'Weather', value: 'Raining' },
      { key: 'Pitch', value: 'Grass' },
      { key: 'Home/Away', value: 'Home' },
    ],
  },
  {
    id: 'sample-2',
    title: 'U16 cup quarter-final',
    match_date: '2026-09-20',
    home_team: 'Northside U16',
    away_team: 'Eastfield U16',
    status: 'done',
    stage: 'done',
    progress: 100,
    created_at: '2026-09-21T09:02:00Z',
    duration_seconds: 4800,
    video_type: 'broadcast',
    resolution: '1280x720',
    thumbnail_url: null,
    tags: [
      { key: 'Weather', value: 'Sunny' },
      { key: 'Pitch', value: 'Turf' },
      { key: 'Competition', value: 'Cup' },
      { key: 'Attendance', value: 'Few fans' },
    ],
  },
  {
    id: 'sample-1',
    title: 'Pre-season friendly',
    match_date: '2026-09-06',
    home_team: 'Northside FC',
    away_team: 'Old Boys XI',
    status: 'failed',
    stage: 'failed',
    error_message: 'Could not detect the pitch in the first minutes of video.',
    created_at: '2026-09-07T18:45:00Z',
    duration_seconds: 3120,
    thumbnail_url: null,
  },
];

// SAMPLE ONLY: a fixed, made-up season used by the Insights page in demo mode or
// when the backend is unreachable. Always shown with a "sample data" banner.
const SAMPLE_SEASON = [
  // [date, weather, pitch, home/away, distance factor, speed factor, result]
  ['2026-08-02', 'Sunny', 'Grass', 'Home', 1.0, 1.0, 'W'],
  ['2026-08-09', 'Raining', 'Grass', 'Away', 0.93, 0.96, 'L'],
  ['2026-08-16', 'Sunny', 'Turf', 'Home', 1.04, 1.02, 'W'],
  ['2026-08-23', 'Raining', 'Turf', 'Home', 0.95, 0.97, 'D'],
  ['2026-08-30', 'Cloudy', 'Grass', 'Away', 0.99, 1.0, 'D'],
  ['2026-09-06', 'Raining', 'Grass', 'Away', 0.9, 0.95, 'L'],
  ['2026-09-13', 'Sunny', 'Grass', 'Home', 1.02, 1.01, 'W'],
  ['2026-09-20', 'Raining', 'Turf', 'Home', 0.94, 0.98, 'W'],
  ['2026-09-27', 'Cloudy', 'Grass', 'Away', 0.97, 0.99, null],
];
const RISKS = ['Low', 'Medium', 'High'];

export const SAMPLE_INSIGHT_MATCHES = SAMPLE_SEASON.map(([date, weather, pitch, ha, df, sf, result], i) => ({
  video: {
    id: `sample-season-${i + 1}`,
    title: `Sample match ${i + 1}`,
    match_date: date,
    result,
    status: 'done',
    stage: 'done',
    tags: [
      { key: 'Weather', value: weather },
      { key: 'Pitch', value: pitch },
      { key: 'Home/Away', value: ha },
    ],
  },
  stats: SAMPLE_PLAYERS.map((p, j) => ({
    ...p,
    top_speed_mph: Math.round(p.top_speed_mph * sf * 10) / 10,
    distance_km: Math.round(p.distance_km * df * 100) / 100,
    injury_risk: RISKS[(j + i + (df < 0.95 ? 1 : 0)) % 3],
  })),
}));


// Demo roster for the Players page (backend v0.6.0 shape).
export const SAMPLE_ROSTER = [
  {
    player_id: 21, team_id: 1, first_name: 'Faisal', last_name: 'Musa', jersey_number: 10, position: 'MF',
    dominant_foot: 'Right', contract_end_date: '2027-06-30', created_at: '2026-09-01T12:00:00Z',
    team: { team_id: 1, team_name: 'Capstone FC', league: 'College Premier', created_at: '2026-09-01T12:00:00Z' },
  },
  {
    player_id: 7, team_id: 1, first_name: 'Luka', last_name: 'Petrovic', jersey_number: 7, position: 'FW',
    dominant_foot: 'Left', contract_end_date: null, created_at: '2026-09-01T12:00:00Z',
    team: { team_id: 1, team_name: 'Capstone FC', league: 'College Premier', created_at: '2026-09-01T12:00:00Z' },
  },
  {
    player_id: 1, team_id: 1, first_name: 'Ivan', last_name: 'Horvat', jersey_number: 1, position: 'GK',
    dominant_foot: 'Right', contract_end_date: '2026-12-31', created_at: '2026-09-01T12:00:00Z',
    team: { team_id: 1, team_name: 'Capstone FC', league: 'College Premier', created_at: '2026-09-01T12:00:00Z' },
  },
  {
    player_id: 30, team_id: 2, first_name: 'Unknown', last_name: '', jersey_number: null, position: 'Unassigned',
    dominant_foot: null, contract_end_date: null, created_at: '2026-10-01T12:00:00Z',
    team: { team_id: 2, team_name: 'Rival United', league: null, created_at: '2026-09-01T12:00:00Z' },
  },
];

// Demo roster risk (backend v0.7.0 provisional shape). Sample values only.
const CFC = { team_id: 1, team_name: 'Capstone FC' };
const RIVAL = { team_id: 2, team_name: 'Rival United' };
const feat = (o) => ({ distance_km: null, sprint_count: null, minutes_played: null, top_speed_kmh: null, hsr_distance_km: null, accels: null, decels: null, heart_rate_avg: null, heart_rate_max: null, ...o });
export const SAMPLE_ROSTER_RISK = {
  team_id: null, match_id: null, sort: 'desc', model_version: 'sample', thresholds: { red: 70, yellow: 40 }, generated_at: '2026-10-08T12:00:00Z', latency_ms: null,
  players: [
    {
      player_id: 7, name: 'Luka Petrovic', first_name: 'Luka', last_name: 'Petrovic', jersey_number: 7, position: 'FW', team: CFC, risk_percent: 76, level: 'red', score_status: 'scored', score_note: null, data_quality: 'demo', source: 'match', match_id: 3, match_date: '2026-10-04', video_id: 3, model_version: 'sample', computed_at: '2026-10-05T09:00:00Z',
      features: feat({ distance_km: 10.8, sprint_count: 31, minutes_played: 90, top_speed_kmh: 33.1, hsr_distance_km: 1.2 }),
      factors: [
        { feature: 'sprint_count', label: 'Sprints', value: 31, contribution: 0.82, direction: 'up' },
        { feature: 'distance_km', label: 'Distance', value: 10.8, contribution: 0.51, direction: 'up' },
        { feature: 'minutes_played', label: 'Minutes played', value: 90, contribution: 0.2, direction: 'up' },
      ],
    },
    {
      player_id: 21, name: 'Faisal Musa', first_name: 'Faisal', last_name: 'Musa', jersey_number: 10, position: 'MF', team: CFC, risk_percent: 48, level: 'yellow', score_status: 'scored', score_note: null, data_quality: 'demo', source: 'csv', match_id: null, match_date: '2026-10-06', video_id: null, model_version: 'sample', computed_at: '2026-10-06T18:00:00Z',
      features: feat({ distance_km: 9.4, minutes_played: 75, heart_rate_avg: 152, heart_rate_max: 188, sprint_count: 19 }),
      factors: [
        { feature: 'heart_rate_max', label: 'Max heart rate', value: 188, contribution: 0.44, direction: 'up' },
        { feature: 'minutes_played', label: 'Minutes played', value: 75, contribution: -0.18, direction: 'down' },
        { feature: 'sprint_count', label: 'Sprints', value: 19, contribution: 0.12, direction: 'up' },
      ],
    },
    {
      player_id: 1, name: 'Ivan Horvat', first_name: 'Ivan', last_name: 'Horvat', jersey_number: 1, position: 'GK', team: CFC, risk_percent: 12, level: 'green', score_status: 'scored', score_note: null, data_quality: 'demo', source: 'match', match_id: 3, match_date: '2026-10-04', video_id: 3, model_version: 'sample', computed_at: '2026-10-05T09:00:00Z',
      features: feat({ distance_km: 4.1, sprint_count: 2, minutes_played: 90, top_speed_kmh: 21.5 }),
      factors: [
        { feature: 'sprint_count', label: 'Sprints', value: 2, contribution: -0.9, direction: 'down' },
        { feature: 'distance_km', label: 'Distance', value: 4.1, contribution: -0.4, direction: 'down' },
      ],
    },
    {
      player_id: 9, name: 'Andrej Kovac', first_name: 'Andrej', last_name: 'Kovac', jersey_number: 9, position: 'FW', team: CFC, risk_percent: null, level: 'unknown', score_status: 'uncalibrated', score_note: 'Broadcast video: needs a custom pitch calibration', data_quality: null, source: 'match', match_id: 3, match_date: '2026-10-04', video_id: 3, model_version: 'sample', computed_at: '2026-10-05T09:00:00Z',
      features: feat({ minutes_played: 90 }), factors: [],
    },
    {
      player_id: 30, name: 'Unknown', first_name: 'Unknown', last_name: '', jersey_number: null, position: 'Unassigned', team: RIVAL, risk_percent: null, level: 'unknown', score_status: 'no_data', score_note: 'No workload data yet', data_quality: null, source: null, match_id: null, match_date: null, video_id: null, model_version: 'sample', computed_at: null,
      features: feat({}), factors: [],
    },
  ],
};
