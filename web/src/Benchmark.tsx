import { useState } from 'react';
import type { BenchmarkEvaluation, Scenario, System } from './types';

const scenarios: Scenario[] = ['clean', 'overlap', 'crossing', 'lifecycle', 'noisy', 'delayed', 'turning'];
const labels: Record<Scenario, string> = { clean: 'Clean tracking', overlap: 'Sensor overlap', crossing: 'Crossing paths', lifecycle: 'Births and deaths', noisy: 'Noise and outages', delayed: 'Delayed reports', turning: 'Turns' };
const fmt = (value: number | null | undefined, digits = 1) => value == null ? 'No score' : value.toFixed(digits);

export function Benchmark({ evaluations, systems, busy, loading, onLaunch, onInspect }: {
  evaluations: BenchmarkEvaluation[]; systems: System[]; busy: boolean; loading: boolean;
  onLaunch: (ids: string[]) => void; onInspect: (caseId: string, runId: string) => void;
}) {
  const [systemIds, setSystemIds] = useState(['kalman', 'nearest']);
  const [suiteId, setSuiteId] = useState('');
  const [rowId, setRowId] = useState('');
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const suites = [...new Set(evaluations.flatMap(e => e.suite_id ? [e.suite_id] : []))];
  const currentSuite = suites.includes(suiteId) ? suiteId : suites[0];
  const included = evaluations.filter(e => e.suite_id === currentSuite || !e.suite_id);
  const rows = included.flatMap(e => e.systems.map(system => ({
    key: `${e.evaluation_id}/${system.spec.id}`, evaluation: e, system,
  })));
  const selected = rows.find(row => row.key === rowId) ?? rows[0];
  const result = selected?.system.result;
  const available = systems.filter(system => system.modes.includes('ungrouped'));
  const eligibleIds = systemIds.filter(id => available.some(system => system.id === id));
  return <section className="benchmark" aria-label="Fixed benchmark scores">
    <div className="section-line"><h2>Benchmark scores</h2><span>Numeric tracking v1 · Higher points are better</span></div>
    <div className="benchmark-scope">28 fixed evaluation cases · 7 equally weighted scenarios · 3 attempts per system</div>
    <details className="benchmark-launch" open={!evaluations.length}><summary>Run the benchmark</summary>
      <fieldset><legend>Systems to evaluate</legend>{available.map(system => <label className="inline" key={system.id}><input type="checkbox" checked={eligibleIds.includes(system.id)} onChange={e => setSystemIds(ids => e.target.checked ? [...ids, system.id] : ids.filter(id => id !== system.id))} />{system.name}</label>)}</fieldset>
      <div className="actions"><button className="primary" disabled={busy || !eligibleIds.length} onClick={() => onLaunch(eligibleIds)}>Run benchmark · {eligibleIds.length * 84} runs</button><span>Preserves system versions. All 84 runs per system must succeed.</span></div>
    </details>
    {suites.length > 0 && <div className="benchmark-definition"><label>Benchmark definition<select value={currentSuite} onChange={e => { setSuiteId(e.target.value); setRowId(''); setScenario(null); }}>{suites.map(id => <option value={id} key={id}>Numeric tracking v1 · {id.slice(0, 12)}</option>)}</select></label><details><summary>Definition fingerprint</summary><code>{currentSuite}</code><p>Only results with this same definition appear together.</p></details></div>}
    {loading ? <p className="empty">Loading benchmark results…</p> : !rows.length ? <p className="empty">{included.some(e => e.status === 'running') ? 'Preparing fixed cases and preserving system versions…' : 'No benchmark score yet. Run the fixed suite above. Saved tuning runs remain available below.'}</p> : <>
      <div className="table-scroll"><table className="benchmark-matrix"><thead><tr><th>System / evaluation</th><th>Overall / 100</th>{scenarios.map(s => <th key={s}>{labels[s]}</th>)}<th>Attempt range</th><th>Status</th></tr></thead><tbody>{rows.map(({ key, evaluation, system }) => <tr key={key} className={selected?.key === key ? 'selected' : ''}>
        <td><button className="text-button" aria-pressed={selected?.key === key} onClick={() => { setRowId(key); setScenario(null); }}>{system.spec.name}</button><span className="version">{system.system_hash.slice(0, 8)} · evaluation {evaluation.evaluation_id.slice(0, 6)}</span></td>
        <td className="overall-score">{fmt(system.result?.score)}</td>
        {scenarios.map(s => <td key={s}>{system.result ? <button className="text-button" aria-label={`${system.spec.name}, ${labels[s]}, evaluation ${evaluation.evaluation_id.slice(0, 6)}`} onClick={() => { setRowId(key); setScenario(s); }}>{fmt(system.result.scenarios.find(value => value.scenario === s)?.score)}</button> : 'Not scored'}</td>)}
        <td>{system.result ? `${fmt(system.result.range.min)}–${fmt(system.result.range.max)}` : 'Unavailable'}</td>
        <td>{system.status}<span className="version">{system.slots.filter(slot => slot.run_id).length} / 84 runs saved</span></td>
      </tr>)}</tbody></table></div>
      {selected?.system.error && <p role="alert" className="notice">No score: {selected.system.error}</p>}
      {result && <div className="benchmark-detail"><section><h3>{selected.system.spec.name} · Behind the score</h3><dl><dt>Identity switches</dt><dd>{result.summary.identity_switches}</dd><dt>Missed object states</dt><dd>{result.summary.missed_states}</dd><dt>False track states</dt><dd>{result.summary.false_states}</dd><dt>Matched coverage</dt><dd>{fmt(result.summary.coverage == null ? null : result.summary.coverage * 100)}%</dd><dt>95th-percentile response</dt><dd>{fmt(result.latency_p95_ms, 2)} ms</dd></dl><p>Counts cover all 84 runs. Identity and response time do not affect these reconstruction points.</p><p>Attempt scores: {result.attempt_scores.map(score => fmt(score, 2)).join(', ')}. The range describes three repeats, not a confidence interval.</p></section>
        <section><h3>Raw error by scenario</h3><div className="table-scroll"><table><thead><tr><th>Scenario</th><th>GOSPA, m</th><th>Points</th></tr></thead><tbody>{result.scenarios.map(value => <tr key={value.scenario}><td><button className="text-button" onClick={() => setScenario(value.scenario)}>{labels[value.scenario]}</button></td><td>{fmt(value.mean_gospa_m, 2)}</td><td>{fmt(value.score)}</td></tr>)}</tbody></table></div></section></div>}
      {selected && scenario && result && <section className="benchmark-cases"><h3>{selected.system.spec.name} · {labels[scenario]}</h3><div className="table-scroll"><table><thead><tr><th>Attempt</th><th>Evaluation seed</th><th>Points</th><th>GOSPA, m</th><th>Inspect</th></tr></thead><tbody>{result.runs.filter(run => run.scenario === scenario).map(run => <tr key={run.run_id}><td>{run.attempt + 1}</td><td>{run.seed}</td><td>{fmt(run.score)}</td><td>{fmt(run.mean_gospa_m, 2)}</td><td><button onClick={() => onInspect(run.case_id, run.run_id)}>Open playback · {run.run_id.slice(0, 6)}</button></td></tr>)}</tbody></table></div></section>}
      {selected && !result && selected.system.slots.some(slot => slot.run_id) && <details className="benchmark-cases"><summary>Inspect saved runs from this evaluation</summary><div className="event-list">{selected.system.slots.filter(slot => slot.run_id).map(slot => <button key={`${slot.attempt}/${slot.case_id}`} onClick={() => { if (slot.run_id) onInspect(slot.case_id, slot.run_id); }}>Attempt {slot.attempt + 1} · {slot.run_id?.slice(0, 6)}</button>)}</div></details>}
    </>}
    {included.filter(e => e.error).map(e => <p className="notice" role="alert" key={e.evaluation_id}>{e.error}</p>)}
    <details className="benchmark-rules"><summary>How the score works</summary><p>100 means perfect reconstruction. Each run is scored against an empty tracker on the same case. An empty tracker earns 0; worse errors also earn 0. Points are not percent accuracy. Raw error distinguishes results at the floor.</p><p>Each scenario contributes one seventh of the total. The final score averages three complete attempts over the same 28 cases. Missing or failed runs prevent a headline score for that system. Tuning, grouped control and custom experiments are excluded.</p><p>The definition fingerprint preserves the cases, scoring implementation, dependencies and response budgets. Each request allows 5 seconds; initialization allows 30 seconds. Runtime depends on the machine. Cost is not measured.</p></details>
  </section>;
}
