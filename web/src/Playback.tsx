import { useEffect, useMemo, useRef, useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import type { Detail, Point } from './types';
import { inputsAtTime } from './playback-data';

const position = (point: Point) => point.map(value => value.toFixed(2)).join(', ');
const seconds = (timeMs: number) => `${Number((timeMs / 1000).toFixed(3))} s`;

export function Plot({ detail, timeMs, reports, domain }: { detail: Detail; timeMs: number; reports: boolean; domain: number[] }) {
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const observer = new ResizeObserver(entries => {
      const entry = entries[0];
      if (entry) setWidth(Math.max(220, Math.round(entry.contentRect.width)));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const [minX = -5, maxX = 100, minY = -5, maxY = 80] = domain;
  const height = 300, left = 44, right = width - 18, top = 24, bottom = height - 38;
  const x = (value: number) => left + (value - minX) / (maxX - minX) * (right - left);
  const y = (value: number) => bottom - (value - minY) / (maxY - minY) * (bottom - top);
  const truth = detail.truth.find(f => f.time_ms === timeMs)?.objects ?? [];
  const snapshot = detail.outputs.find(f => f.time_ms === timeMs);
  const observations = snapshot ? detail.requests.find(f => f.time_ms === timeMs)?.observations ?? [] : [];
  const metric = detail.metrics?.ticks.find(frame => frame.time_ms === timeMs);
  const trails = (kind: 'truth' | 'estimate') => {
    const paths = new Map<string, { path: string; time: number }>();
    const frames = kind === 'truth'
      ? detail.truth.map(f => ({ time: f.time_ms, points: f.objects.map(o => ({ id: o.truth_id, point: o.position_m })) }))
      : detail.outputs.map(f => ({ time: f.time_ms, points: f.tracks.map(o => ({ id: o.track_id, point: o.position_m })) }));
    for (const frame of frames) {
      if (frame.time > timeMs || frame.time < timeMs - 15000) continue;
      for (const { id, point } of frame.points) {
        const previous = paths.get(id);
        paths.set(id, { path: `${previous?.path ?? ''}${previous && frame.time - previous.time === 500 ? 'L' : 'M'}${x(point[0])},${y(point[1])}`, time: frame.time });
      }
    }
    return [...paths].map(([id, value]) => <path key={id} d={value.path} className={kind} />);
  };
  const pointLabel = (p: Point) => `${p[0].toFixed(2)}, ${p[1].toFixed(2)} m`;
  return <div ref={container} className="plot-container">
    <svg viewBox={`0 0 ${width} ${height}`} className="plot" role="img" aria-label={`${detail.result.system.name}, truth and estimates at ${timeMs / 1000} seconds`}>
      <title>Circles: truth. Squares: estimates. Dotted connectors: evaluator matches. Crosses: confirmed new reports. Trails: last 15 seconds.</title>
      {[0, 0.5, 1].map(f => <g key={f} className="grid">
        <line x1={x(minX + f * (maxX - minX))} x2={x(minX + f * (maxX - minX))} y1={top} y2={bottom} />
        <line x1={left} x2={right} y1={y(minY + f * (maxY - minY))} y2={y(minY + f * (maxY - minY))} />
        <text x={x(minX + f * (maxX - minX))} y={bottom + 18} textAnchor="middle">{Math.round(minX + f * (maxX - minX))}</text>
        <text x={left - 8} y={y(minY + f * (maxY - minY)) + 4} textAnchor="end">{Math.round(minY + f * (maxY - minY))}</text>
      </g>)}
      <text x={left} y={14}>y (m)</text><text x={right} y={height - 3} textAnchor="end">x (m)</text>
      {trails('truth')}{trails('estimate')}
      {metric?.matches.map(match => {
        const actual = truth.find(obj => obj.truth_id === match.truth_id);
        const estimate = snapshot?.tracks.find(obj => obj.track_id === match.track_id);
        return actual && estimate && <line key={match.track_id} className="match-link" x1={x(actual.position_m[0])} y1={y(actual.position_m[1])} x2={x(estimate.position_m[0])} y2={y(estimate.position_m[1])}><title>{match.truth_id} to {match.track_id}: {match.distance_m.toFixed(2)} m</title></line>;
      })}
      {truth.map((obj, index) => <g key={obj.truth_id}><circle cx={x(obj.position_m[0])} cy={y(obj.position_m[1])} r={5} className="truth"><title>{obj.truth_id}: {pointLabel(obj.position_m)}</title></circle>{truth.length <= 6 && <text x={x(obj.position_m[0]) - 8} y={y(obj.position_m[1]) + (index % 2 ? 20 : -10)} textAnchor="end">{obj.truth_id}</text>}</g>)}
      {snapshot?.tracks.map(obj => <g key={obj.track_id}><rect x={x(obj.position_m[0]) - 4} y={y(obj.position_m[1]) - 4} width={8} height={8} className="estimate"><title>{obj.track_id}: {pointLabel(obj.position_m)}</title></rect>{snapshot.tracks.length <= 6 && <text x={x(obj.position_m[0]) + 8} y={y(obj.position_m[1]) - 10}>{obj.track_id}</text>}</g>)}
      {reports && observations.map(obs => <path key={obs.observation_id} className="observation" d={`M${x(obs.position_m[0]) - 3},${y(obs.position_m[1]) - 3}l6,6m0,-6l-6,6`}><title>{obs.sensor_id}, measured {obs.measured_at_ms / 1000}s, arrived {obs.arrived_at_ms / 1000}s</title></path>)}
    </svg>
    {!snapshot && <p className="notice">No recorded output at this tick. {detail.result.status === 'failed' ? 'The run failed.' : 'The run has not reached this tick.'}</p>}
  </div>;
}

function TruthComparison({ detail, timeMs }: { detail: Detail; timeMs: number }) {
  const actual = detail.truth.find(frame => frame.time_ms === timeMs)?.objects ?? [];
  const output = detail.outputs.find(frame => frame.time_ms === timeMs);
  const metric = detail.metrics?.ticks.find(frame => frame.time_ms === timeMs);
  const unmatched = metric ? output?.tracks.filter(track => !metric.matches.some(match => match.track_id === track.track_id)) ?? [] : [];
  return <div className="truth-comparison">
    <h3>Truth compared with the estimate</h3>
    <p>{actual.length} actual objects · {output ? `${output.tracks.length} estimated ${output.tracks.length === 1 ? 'track' : 'tracks'}` : 'No recorded response'}{metric && ` · ${metric.missed_ids.length} missed · ${metric.false_ids.length} false`}</p>
    <div className="table-scroll"><table><thead><tr><th>Actual object</th><th>Truth x, y · m</th><th>System x, y · m</th><th>Error / status</th></tr></thead><tbody>
      {actual.map(object => {
        const match = metric?.matches.find(value => value.truth_id === object.truth_id);
        const estimate = output?.tracks.find(track => track.track_id === match?.track_id);
        return <tr key={object.truth_id}><td>{object.truth_id}</td><td>{position(object.position_m)}</td><td>{estimate ? <>{estimate.track_id}<br />{position(estimate.position_m)}</> : output && metric ? 'No matched estimate' : 'Unavailable'}</td><td>{match ? <>{match.distance_m.toFixed(2)} m{match.identity_switch && <><br />Identity switched</>}</> : metric ? 'Missed object' : 'Not scored'}</td></tr>;
      })}
      {unmatched.map(track => <tr key={`false-${track.track_id}`}><td>No truth match</td><td>Not applicable</td><td>{track.track_id}<br />{position(track.position_m)}</td><td>False track</td></tr>)}
      {!actual.length && !unmatched.length && <tr><td colSpan={4}>{metric ? 'No actual objects or false tracks at this time.' : 'No scored associations at this time.'}</td></tr>}
    </tbody></table></div>
    <p>Matches come from the evaluator. Ground truth is not sent to the system.</p>
  </div>;
}

function ReportTable({ rows, timeMs, grouped }: { rows: ReturnType<typeof inputsAtTime>['history']; timeMs: number; grouped: boolean }) {
  return <div className="table-scroll"><table className="input-table"><thead><tr><th>Source</th><th>Measured</th><th>Arrived</th><th>Given to system</th><th>Age now</th><th>x, y · m</th>{grouped && <th>Oracle group</th>}</tr></thead><tbody>
    {rows.map(({ observation: report, givenAt }) => <tr key={report.observation_id}><td>{report.sensor_id}<details><summary>Report details</summary><code>{report.observation_id}</code><br />σ x: {Math.sqrt(report.position_cov_m2[0][0]).toFixed(2)} m<br />σ y: {Math.sqrt(report.position_cov_m2[1][1]).toFixed(2)} m</details></td><td>{seconds(report.measured_at_ms)}</td><td>{seconds(report.arrived_at_ms)}</td><td>{seconds(givenAt)}</td><td>{seconds(timeMs - report.measured_at_ms)}</td><td>{position(report.position_m)}</td>{grouped && <td><code>{report.group_key}</code></td>}</tr>)}
  </tbody></table></div>;
}

function InputPanel({ detail, timeMs }: { detail: Detail; timeMs: number }) {
  const { request, confirmed, batch, history } = inputsAtTime(detail, timeMs);
  const [historyLimit, setHistoryLimit] = useState(50);
  const grouped = detail.result.mode === 'grouped';
  return <section className="input-panel" aria-label={`Inputs for ${detail.result.system.name}`}>
    <h3>Inputs at {seconds(timeMs)}</h3>
    <p>{confirmed ? `${batch.length} new reports` : 'Current delivery unconfirmed'} · {history.length} confirmed received so far</p>
    {grouped && <p className="notice">Grouped control: oracle group keys supplied; clutter removed.</p>}
    {confirmed ? batch.length ? <ReportTable rows={batch.map(observation => ({ observation, givenAt: timeMs }))} timeMs={timeMs} grouped={grouped} /> : <p className="input-empty">No new reports this step. Received history is listed below.</p> : <p className="notice">No valid response confirms receipt at this step. Recorded requests may not have been sent and are excluded from the received history.</p>}
    <details className="input-history"><summary>All inputs received through {seconds(timeMs)} · {history.length} reports</summary>
      {history.length ? <><p>Most recent first · showing {Math.min(historyLimit, history.length)} of {history.length}</p><ReportTable rows={history.slice(0, historyLimit)} timeMs={timeMs} grouped={grouped} />{historyLimit < history.length && <button onClick={() => setHistoryLimit(limit => limit + 50)}>Show 50 more reports</button>}</> : <p>No confirmed reports yet.</p>}
    </details>
    <details><summary>{confirmed ? 'Exact input message for this step' : 'Recorded request · delivery unconfirmed'}</summary><pre>{request ? JSON.stringify(request, null, 2) : 'No request recorded at this time.'}</pre></details>
    <details><summary>Setup information given before the run</summary><p>{detail.result.initialization_ms != null || detail.outputs.length ? 'Initialization acknowledged.' : 'Initialization delivery is unconfirmed.'}</p><pre>{JSON.stringify(detail.init, null, 2)}</pre></details>
    <p className="input-boundary">Received history shows confirmed delivery, not what the system remembered or used internally. Future reports are excluded.</p>
  </section>;
}

export function Playback({ detail, comparison, tick, setTick }: { detail: Detail; comparison: Detail | null; tick: number; setTick: Dispatch<SetStateAction<number>> }) {
  const [playing, setPlaying] = useState(false);
  const [reports, setReports] = useState(false);
  const maxTick = detail.truth.length - 1;
  const domain = useMemo(() => {
    const bounds = { minX: 0, maxX: 20, minY: 0, maxY: 20 };
    for (const run of comparison ? [detail, comparison] : [detail]) {
      const points = [...run.truth.flatMap(f => f.objects.map(o => o.position_m)),
        ...run.outputs.flatMap(f => f.tracks.map(t => t.position_m)),
        ...run.requests.flatMap(f => f.observations.map(o => o.position_m))];
      for (const [x, y] of points) {
        bounds.minX = Math.min(bounds.minX, x); bounds.maxX = Math.max(bounds.maxX, x);
        bounds.minY = Math.min(bounds.minY, y); bounds.maxY = Math.max(bounds.maxY, y);
      }
    }
    return [bounds.minX - 5, bounds.maxX + 5, bounds.minY - 5, bounds.maxY + 5];
  }, [detail, comparison]);
  useEffect(() => { setPlaying(false); }, [detail.result.case_id]);
  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => setTick(value => {
      if (value >= maxTick) { setPlaying(false); return value; }
      return value + 1;
    }), 500);
    return () => clearInterval(timer);
  }, [playing, maxTick, setTick]);
  const timeMs = detail.truth[tick]?.time_ms ?? 0;
  const events = (detail.metrics?.ticks ?? []).filter((value, i, values) =>
    value.matches.some(match => match.identity_switch) ||
    value.missed_ids.length > (values[i - 1]?.missed_ids.length ?? 0) ||
    value.false_ids.length > (values[i - 1]?.false_ids.length ?? 0));
  return <section className="replay" aria-label="Synchronized playback">
    <div className="section-line"><h2>Ground truth, estimates and inputs</h2><label className="inline"><input type="checkbox" checked={reports} onChange={e => setReports(e.target.checked)} /> Show input reports on plots</label></div>
    <div className="scrub">
      <button onClick={() => { if (tick >= maxTick) setTick(0); setPlaying(!playing); }}>{playing ? 'Pause' : 'Play'}</button>
      <button aria-label="Previous tick" disabled={tick === 0} onClick={() => setTick(tick - 1)}>−0.5 s</button>
      <label className="time-control">Time<input aria-label="Simulation time" type="range" min={0} max={maxTick} value={tick} onChange={e => { setTick(Number(e.target.value)); setPlaying(false); }} /></label>
      <output>{(timeMs / 1000).toFixed(1)} / {(detail.truth.at(-1)?.time_ms ?? 0) / 1000} s</output>
      <button aria-label="Next tick" disabled={tick === maxTick} onClick={() => setTick(tick + 1)}>+0.5 s</button>
    </div>
    <div className="legend"><span><i className="truth-key" />Truth ○</span><span><i className="estimate-key" />Estimate □</span><span>Dotted line: matched error</span>{reports && <span>Input report ×</span>}<span>Trails: 15 s</span></div>
    {(comparison ? [detail, comparison] : [detail]).map(run => <div className="transparency-row" key={run.result.run_id}>
      <section className="scene-panel" aria-label={`Truth and estimates for ${run.result.system.name}`}><h3>{run.result.system.name} · {run.result.system.version}</h3><Plot detail={run} timeMs={timeMs} reports={reports} domain={domain} /><TruthComparison detail={run} timeMs={timeMs} /></section>
      <InputPanel detail={run} timeMs={timeMs} />
    </div>)}
    <div className="playback-events"><h3>Jump to an error · {detail.result.system.name}</h3><div className="event-list">{events.length ? events.slice(0, 30).map(event => <button key={event.time_ms} onClick={() => { setTick(event.time_ms / 500); setPlaying(false); }}>{event.time_ms / 1000} s · {event.matches.some(m => m.identity_switch) ? 'Identity switch' : event.missed_ids.length ? 'Missed object' : 'False track'}</button>) : <p>{detail.metrics?.ticks.length ? 'No tracking errors detected in scored steps.' : 'No scored steps available.'}</p>}</div>{events.length > 30 && <p>First 30 events shown. Full associations are saved with the run.</p>}</div>
  </section>;
}
