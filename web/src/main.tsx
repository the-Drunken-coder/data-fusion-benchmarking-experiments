import { StrictMode, useCallback, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { api } from './api';
import { Playback } from './Playback';
import { Benchmark } from './Benchmark';
import type { Catalog, Config, Detail, Job, Mode, Run, Scenario } from './types';
import './style.css';

const labels: Record<Scenario, string> = { clean: 'One object', overlap: 'Overlapping sensors', crossing: 'Crossing paths', lifecycle: 'Appearance and disappearance', noisy: 'Misses, clutter and outage', delayed: 'Delayed reports', turning: 'Turning objects' };
const fmt = (value: number | null | undefined, digits = 2) => value == null ? 'Unavailable' : value.toFixed(digits);
const message = (error: unknown) => error instanceof Error ? error.message : String(error);

function App() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState('');
  const [caseId, setCaseId] = useState('');
  const [runId, setRunId] = useState('');
  const [compareId, setCompareId] = useState('');
  const [mode, setMode] = useState<Mode>('ungrouped');
  const [detail, setDetail] = useState<Detail | null>(null);
  const [comparison, setComparison] = useState<Detail | null>(null);
  const [playbackTick, setPlaybackTick] = useState(0);
  const [job, setJob] = useState<Job | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [config, setConfig] = useState<Config>({ scenario: 'crossing', seed: 100, partition: 'tuning', kind: 'fixed' });
  const [selectedSystems, setSelectedSystems] = useState(['kalman', 'nearest']);
  const refresh = useCallback(async () => {
    const value = await api<Catalog>('/api/catalog');
    setCatalog(value);
    return value;
  }, []);
  useEffect(() => { refresh().then(value => {
    setCaseId(value.runs[0]?.case_id ?? value.cases[0]?.case_id ?? '');
    const active = value.jobs.find(value => value.status === 'running');
    if (active) setJob(active);
  }).catch(error => setError(message(error))); }, [refresh]);
  useEffect(() => {
    if (!job || job.status !== 'running') return;
    let stopped = false;
    let timer: number;
    const poll = async () => {
      try {
        const next = await api<Job>(`/api/jobs/${job.job_id}`);
        if (stopped) return;
        setJob(next);
        await refresh();
        if (next.status !== 'running') {
          if (next.case_id) setCaseId(next.case_id);
          setRunId(next.run_ids.at(-1) ?? '');
          if (next.error) setError(next.error);
        }
      } catch (error) { if (!stopped) setError(message(error)); }
      if (!stopped) timer = window.setTimeout(poll, 1000);
    };
    timer = window.setTimeout(poll, 500);
    return () => { stopped = true; clearTimeout(timer); };
  }, [job?.job_id, job?.status, refresh]);
  const cases = catalog?.cases ?? [];
  const currentCase = cases.find(value => value.case_id === caseId);
  useEffect(() => { setPlaybackTick(0); }, [caseId]);
  const runs = catalog?.runs.filter(run => run.case_id === caseId && run.mode === mode) ?? [];
  const selected = runs.find(run => run.run_id === runId) ?? runs[0];
  const peer = runs.find(run => run.run_id === compareId && run.run_id !== selected?.run_id);
  useEffect(() => {
    let stopped = false;
    setDetail(null);
    if (selected) api<Detail>(`/api/runs/${selected.run_id}`).then(value => { if (!stopped) setDetail(value); }).catch(error => { if (!stopped) setError(message(error)); });
    return () => { stopped = true; };
  }, [selected?.run_id, selected?.status]);
  useEffect(() => {
    let stopped = false;
    setComparison(null);
    if (peer) api<Detail>(`/api/runs/${peer.run_id}`).then(value => { if (!stopped) setComparison(value); }).catch(error => { if (!stopped) setError(message(error)); });
    return () => { stopped = true; };
  }, [peer?.run_id, peer?.status]);
  async function launch(suite: boolean) {
    setError(''); setSubmitting(true);
    try {
      const next = await api<Job>('/api/experiments', { config, system_ids: selectedSystems, mode, suite });
      setJob(next); setCompareId('');
    } catch (error) { setError(message(error)); }
    finally { setSubmitting(false); }
  }
  async function launchBenchmark(ids: string[]) {
    setError(''); setSubmitting(true);
    try { setJob(await api<Job>('/api/benchmarks', { system_ids: ids })); }
    catch (error) { setError(message(error)); }
    finally { setSubmitting(false); }
  }
  function inspectBenchmark(caseId: string, runId: string) {
    setMode('ungrouped'); setCaseId(caseId); setRunId(runId); setCompareId('');
    document.getElementById('saved-runs')?.scrollIntoView({ block: 'start' });
  }
  function updateConfig(values: Partial<Config>) { setConfig(current => ({ ...current, ...values })); }
  const busy = submitting || job?.status === 'running';
  return <main>
    <header className="chrome"><span className="wordmark">FUSION / LAB</span><span>Local workspace · No paid services</span></header>
    <div className="heading"><div><h1>Compare systems</h1><div className="meta"><span>Numeric tracking / v1</span><span>{currentCase ? labels[currentCase.config.scenario] : 'No case selected'}</span>{currentCase && <span>{currentCase.config.partition} · seed {currentCase.config.seed} · {currentCase.config.kind}</span>}</div></div><button onClick={() => refresh().catch(error => setError(message(error)))}>Refresh runs</button></div>
    {error && <div role="alert" className="error"><span>{error}</span><button onClick={() => setError('')}>Dismiss</button></div>}
    <Benchmark evaluations={catalog?.benchmarks ?? []} systems={catalog?.systems ?? []} busy={busy} loading={!catalog} onLaunch={launchBenchmark} onInspect={inspectBenchmark} />
    <section className="setup"><details open={!catalog?.runs.length}><summary>Run an experiment</summary>
      <div className="fields">
        <label>Conditions<select value={config.kind} onChange={e => setConfig({ scenario: config.scenario, seed: config.seed, partition: config.partition, kind: e.target.value === 'fixed' ? 'fixed' : 'exploratory', ...(e.target.value === 'exploratory' ? { object_count: 2, noise_m: 2, detection_probability: 0.93, outage_ms: 0 } : {}) })}><option value="fixed">Standard conditions</option><option value="exploratory">Exploratory experiment</option></select></label>
        <label>Scenario<select value={config.scenario} onChange={e => { const scenario = catalog?.scenarios.find(value => value === e.target.value); if (scenario) updateConfig({ scenario }); }}>{(catalog?.scenarios ?? []).map(value => <option key={value} value={value}>{labels[value]}</option>)}</select></label>
        <label>Case set<select value={config.partition} onChange={e => { const partition = e.target.value === 'tuning' ? 'tuning' : 'evaluation'; updateConfig({ partition, seed: partition === 'tuning' ? 100 : 1000 }); }}><option value="tuning">Tuning cases</option><option value="evaluation">Held-out evaluation</option></select></label>
        <label>Seed<input type="number" min={0} max={4294967295} value={config.seed} onChange={e => updateConfig({ seed: Number(e.target.value) })} /></label>
        {config.kind === 'exploratory' && <><label>Objects<input type="number" min={1} max={20} value={config.object_count ?? 2} onChange={e => updateConfig({ object_count: Number(e.target.value) })} /></label><label>Noise (m)<input type="number" min={0.1} max={20} step={0.1} value={config.noise_m ?? 2} onChange={e => updateConfig({ noise_m: Number(e.target.value) })} /></label><label>Detection probability<input type="number" min={0} max={1} step={0.05} value={config.detection_probability ?? 0.93} onChange={e => updateConfig({ detection_probability: Number(e.target.value) })} /></label><label>Sensor B outage (s)<input type="number" min={0} max={30} value={(config.outage_ms ?? 0) / 1000} onChange={e => updateConfig({ outage_ms: Number(e.target.value) * 1000 })} /></label></>}
      </div>
      <fieldset><legend>Systems</legend>{catalog?.systems.filter(system => system.modes.includes(mode)).map(system => <label key={system.id} className="inline"><input type="checkbox" checked={selectedSystems.includes(system.id)} onChange={e => setSelectedSystems(current => e.target.checked ? [...current, system.id] : current.filter(id => id !== system.id))} />{system.name} · {system.version}</label>)}</fieldset>
      <div className="actions"><button className="primary" disabled={busy || !selectedSystems.length} onClick={() => launch(false)}>Run selected case</button>{config.kind === 'fixed' && <button disabled={busy || !selectedSystems.length} onClick={() => launch(true)}>Run experiment suite · 7 scenarios × 2 seeds</button>}<span>New runs preserve these conditions. Existing results stay unchanged.</span></div>
      {config.partition === 'evaluation' && <p className="notice">Held-out results are for final evaluation. Freeze system settings before using this case set.</p>}
    </details></section>
    {job && <div className="job" role="status"><span>{job.kind === 'benchmark' ? 'Benchmark' : 'Experiment'} {job.status} · {job.run_ids.length} / {job.requested} runs finished</span>{job.status === 'running' && <progress aria-label="Experiment progress" max={job.requested} value={job.run_ids.length} />}{job.status === 'failed' && <span>Inspect failed runs; partial results are not ranked.</span>}</div>}
    <section className="results" id="saved-runs">
      <div className="filters"><label>Saved case<select value={caseId} onChange={e => { setCaseId(e.target.value); setRunId(''); setCompareId(''); }}>{!cases.length && <option value="">No saved cases</option>}{cases.map(value => <option key={value.case_id} value={value.case_id}>{labels[value.config.scenario]} · {value.config.partition} · seed {value.config.seed} · {value.config.kind} · {value.case_id.slice(0, 6)}</option>)}</select></label><label>Task<select value={mode} onChange={e => { setMode(e.target.value === 'grouped' ? 'grouped' : 'ungrouped'); setCompareId(''); }}><option value="ungrouped">Ungrouped tracking</option><option value="grouped">Grouped control · oracle association</option></select></label></div>
      {mode === 'grouped' && <p className="notice">Oracle association and filtered clutter. These results are separate from ungrouped tracking.</p>}
      <div className="section-line"><h2>Same observations · {runs.length} runs</h2><span>GOSPA and RMSE: lower is better</span></div>
      {!catalog ? <p className="empty">Loading saved experiments…</p> : !runs.length ? <p className="empty">No runs for this case and task. Select systems above and run an experiment.</p> : <div className="table-scroll"><table className="comparison"><thead><tr><th>System / version</th><th>GOSPA</th><th>Position RMSE</th><th>Coverage</th><th>ID switches</th><th>Latency p95</th><th>Status</th></tr></thead><tbody>{runs.map(run => <RunRow key={run.run_id} run={run} active={run.run_id === selected?.run_id} onSelect={() => setRunId(run.run_id)} />)}</tbody></table></div>}
      {runs.length > 0 && <p className="footnote">Position RMSE uses matched states. Coverage and GOSPA expose missing objects. Failed runs show partial values and are excluded from comparisons.</p>}
      {selected?.failure && <p className="error" role="alert">Run failed: {selected.failure}</p>}
      {selected && <div className="section-line"><label>Compare playback with<select value={peer?.run_id ?? ''} onChange={e => setCompareId(e.target.value)}><option value="">Selected run only</option>{runs.filter(run => run.run_id !== selected.run_id).map(run => <option key={run.run_id} value={run.run_id}>{run.system.name} · {run.run_id.slice(0, 6)} · {run.status}</option>)}</select></label><span>Run {selected.run_id} · system {selected.system_hash.slice(0, 10)}</span></div>}
    </section>
    {detail ? <Playback detail={detail} comparison={comparison} tick={playbackTick} setTick={setPlaybackTick} /> : selected && <p className="empty">Loading recorded outputs…</p>}
    {detail?.result.summary && <section className="metrics"><details><summary>Scoring, reliability and artifacts</summary><div className="metric-grid">
      <div><h3>GOSPA components · mean m²</h3><dl><dt>Localization</dt><dd>{fmt(detail.result.summary.gospa_components_mean_m2.localisation)}</dd><dt>Missed objects</dt><dd>{fmt(detail.result.summary.gospa_components_mean_m2.missed)}</dd><dt>False tracks</dt><dd>{fmt(detail.result.summary.gospa_components_mean_m2.false)}</dd></dl><p>p = 2, c = 10 m, α = 2. At each tick, distance is the square root of the component sum.</p></div>
      <div><h3>Association and coverage</h3><dl><dt>Matched / eligible states</dt><dd>{detail.result.summary.matched_states} / {detail.result.summary.eligible_states}</dd><dt>Missed / false states</dt><dd>{detail.result.summary.missed_states} / {detail.result.summary.false_states}</dd><dt>MOTA</dt><dd>{fmt(detail.result.summary.mota)}</dd><dt>MOTP</dt><dd>{fmt(detail.result.summary.motp_m)} m</dd><dt>Velocity RMSE</dt><dd>{fmt(detail.result.summary.velocity_rmse_mps)}{detail.result.summary.velocity_rmse_mps != null ? ' m/s' : ''}</dd></dl><p>CLEAR MOT associations, 10 m gate. Uncertainty scoring unavailable.</p></div>
      <div><h3>Execution</h3><dl><dt>Scored ticks</dt><dd>{detail.result.summary.scored_ticks} / {detail.result.summary.expected_ticks}</dd><dt>Reports delivered / acknowledged</dt><dd>{detail.result.observations_delivered} / {detail.result.observations_acknowledged}</dd><dt>Timeouts / invalid outputs</dt><dd>{detail.result.timeouts} / {detail.result.invalid_outputs}</dd></dl><p>Lockstep replay. Latency excludes generation and scoring; it does not establish real-time capacity.</p><a href={`/api/runs/${detail.result.run_id}/trajectory.svg`}>Download trajectory plot</a> · <a href={`/api/runs/${detail.result.run_id}`} download={`${detail.result.run_id}.json`}>Download recorded results</a></div>
    </div></details></section>}
    <details className="systems"><summary>Available systems and import instructions</summary>{catalog?.systems.map(system => <p key={system.id}><strong>{system.name} {system.version}.</strong> {system.description}</p>)}<p>To add a system, place its program and system.json in a folder, then run <code>uv run fusion register /path/to/folder</code>. Refresh runs to load it. Candidates use JSON Lines; see docs/protocol.md.</p></details>
    <footer>Saved inputs → saved outputs → scores · Truth is visible here, never sent to candidates.</footer>
  </main>;
}

function RunRow({ run, active, onSelect }: { run: Run; active: boolean; onSelect: () => void }) {
  const summary = run.summary;
  const complete = run.status === 'complete';
  return <tr className={active ? 'selected' : ''}><td><button aria-pressed={active} onClick={onSelect}>{run.system.name}</button><span className="version">{run.system.version} · {run.run_id.slice(0, 6)}</span></td><td>{fmt(summary?.mean_gospa_m)}{summary?.mean_gospa_m != null ? ' m' : ''}{!complete && summary && ' *'}</td><td>{fmt(summary?.position_rmse_m)}{summary?.position_rmse_m != null ? ' m' : ''}</td><td>{summary?.coverage == null ? 'Unavailable' : `${(summary.coverage * 100).toFixed(1)}%`}</td><td>{summary?.identity_switches ?? 'Unavailable'}</td><td>{fmt(run.latency_ms?.p95)}{run.latency_ms?.p95 != null ? ' ms' : ''}</td><td>{run.status}{!complete && summary && ' · partial'}</td></tr>;
}

const root = document.getElementById('root');
if (!root) throw new Error('Application root is missing');
createRoot(root).render(<StrictMode><App /></StrictMode>);
