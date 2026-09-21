import { useEffect, useMemo, useRef, useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import type { Detail, Point } from './types';

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
  const observations = detail.requests.find(f => f.time_ms === timeMs)?.observations ?? [];
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
      <title>Circles: truth. Squares: estimates. Crosses: newly arrived sensor reports. Trails: last 15 seconds.</title>
      {[0, 0.5, 1].map(f => <g key={f} className="grid">
        <line x1={x(minX + f * (maxX - minX))} x2={x(minX + f * (maxX - minX))} y1={top} y2={bottom} />
        <line x1={left} x2={right} y1={y(minY + f * (maxY - minY))} y2={y(minY + f * (maxY - minY))} />
        <text x={x(minX + f * (maxX - minX))} y={bottom + 18} textAnchor="middle">{Math.round(minX + f * (maxX - minX))}</text>
        <text x={left - 8} y={y(minY + f * (maxY - minY)) + 4} textAnchor="end">{Math.round(minY + f * (maxY - minY))}</text>
      </g>)}
      <text x={left} y={14}>y (m)</text><text x={right} y={height - 3} textAnchor="end">x (m)</text>
      {trails('truth')}{trails('estimate')}
      {truth.map(obj => <circle key={obj.truth_id} cx={x(obj.position_m[0])} cy={y(obj.position_m[1])} r={5} className="truth"><title>{obj.truth_id}: {pointLabel(obj.position_m)}</title></circle>)}
      {snapshot?.tracks.map(obj => <g key={obj.track_id}><rect x={x(obj.position_m[0]) - 4} y={y(obj.position_m[1]) - 4} width={8} height={8} className="estimate"><title>{obj.track_id}: {pointLabel(obj.position_m)}</title></rect></g>)}
      {reports && observations.map(obs => <path key={obs.observation_id} className="observation" d={`M${x(obs.position_m[0]) - 3},${y(obs.position_m[1]) - 3}l6,6m0,-6l-6,6`}><title>{obs.sensor_id}, measured {obs.measured_at_ms / 1000}s, arrived {obs.arrived_at_ms / 1000}s</title></path>)}
    </svg>
    {!snapshot && <p className="notice">No recorded output at this tick. {detail.result.status === 'failed' ? 'The run failed.' : 'The run has not reached this tick.'}</p>}
  </div>;
}

export function Playback({ detail, comparison, tick, setTick }: { detail: Detail; comparison: Detail | null; tick: number; setTick: Dispatch<SetStateAction<number>> }) {
  const [playing, setPlaying] = useState(false);
  const [reports, setReports] = useState(true);
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
  }, [playing, maxTick]);
  const timeMs = detail.truth[tick]?.time_ms ?? 0;
  const metric = detail.metrics?.ticks.find(f => f.time_ms === timeMs);
  const snapshot = detail.outputs.find(f => f.time_ms === timeMs);
  const batch = detail.requests.find(f => f.time_ms === timeMs)?.observations ?? [];
  const events = (detail.metrics?.ticks ?? []).filter((value, i, values) =>
    value.matches.some(match => match.identity_switch) ||
    value.missed_ids.length > (values[i - 1]?.missed_ids.length ?? 0) ||
    value.false_ids.length > (values[i - 1]?.false_ids.length ?? 0));
  return <section className="replay" aria-label="Synchronized playback">
    <div className="section-line"><h2>Inspect the run</h2><label className="inline"><input type="checkbox" checked={reports} onChange={e => setReports(e.target.checked)} /> Sensor reports</label></div>
    <div className="legend"><span><i className="truth-key" />Truth ○</span><span><i className="estimate-key" />Estimate □</span><span>Sensor report ×</span><span>Trails: 15 s</span></div>
    <div className={comparison ? 'plots paired' : 'plots'}>
      <div><h3>{detail.result.system.name} · {detail.result.system.version}</h3><Plot detail={detail} timeMs={timeMs} reports={reports} domain={domain} /></div>
      {comparison && <div><h3>{comparison.result.system.name} · {comparison.result.system.version}</h3><Plot detail={comparison} timeMs={timeMs} reports={reports} domain={domain} /></div>}
    </div>
    <div className="scrub">
      <button onClick={() => { if (tick >= maxTick) setTick(0); setPlaying(!playing); }}>{playing ? 'Pause' : 'Play'}</button>
      <button aria-label="Previous tick" disabled={tick === 0} onClick={() => setTick(tick - 1)}>−0.5 s</button>
      <label className="time-control">Time<input aria-label="Simulation time" type="range" min={0} max={maxTick} value={tick} onChange={e => { setTick(Number(e.target.value)); setPlaying(false); }} /></label>
      <output>{(timeMs / 1000).toFixed(1)} / 60 s</output>
      <button aria-label="Next tick" disabled={tick === maxTick} onClick={() => setTick(tick + 1)}>+0.5 s</button>
    </div>
    <div className="inspector">
      <div><h3>At this moment</h3><p>{snapshot?.tracks.length ?? 'Unavailable'} tracks · {batch.length} new reports · {metric?.missed_ids.length ?? 'Unavailable'} missed · {metric?.false_ids.length ?? 'Unavailable'} false</p>
        <div className="table-scroll"><table><thead><tr><th>Track</th><th>Truth match</th><th>Error</th><th>Identity</th></tr></thead><tbody>
          {metric?.matches.map(match => <tr key={match.track_id}><td>{match.track_id}</td><td>{match.truth_id}</td><td>{match.distance_m.toFixed(2)} m</td><td>{match.identity_switch ? 'Switched' : 'Continued'}</td></tr>)}
          {!metric?.matches.length && <tr><td colSpan={4}>No matched states at this tick</td></tr>}
        </tbody></table></div>
      </div>
      <div><h3>Jump to an error</h3><div className="event-list">{events.length ? events.slice(0, 30).map(event => <button key={event.time_ms} onClick={() => { setTick(event.time_ms / 500); setPlaying(false); }}>{event.time_ms / 1000} s · {event.matches.some(m => m.identity_switch) ? 'Identity switch' : event.missed_ids.length ? 'Missed object' : 'False track'}</button>) : <p>No tracking errors detected.</p>}</div>{events.length > 30 && <p>First 30 events shown. Full associations are saved with the run.</p>}</div>
    </div>
    <details className="report-details"><summary>Newly arrived observations</summary><div className="table-scroll"><table><thead><tr><th>Source</th><th>Measured</th><th>Arrived</th><th>Position</th></tr></thead><tbody>{batch.map(obs => <tr key={obs.observation_id}><td>{obs.sensor_id}</td><td>{obs.measured_at_ms / 1000} s</td><td>{obs.arrived_at_ms / 1000} s</td><td>{obs.position_m.map(v => v.toFixed(1)).join(', ')} m</td></tr>)}</tbody></table></div></details>
  </section>;
}
