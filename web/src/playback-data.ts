import type { Detail } from './types';

/** Saved requests include future replay steps. Only valid responses confirm receipt. */
export function inputsAtTime(detail: Pick<Detail, 'requests' | 'outputs'>, timeMs: number) {
  const acknowledged = new Set(detail.outputs.map(frame => frame.time_ms));
  const request = detail.requests.find(frame => frame.time_ms === timeMs);
  const confirmed = acknowledged.has(timeMs);
  const history = detail.requests
    .filter(frame => frame.time_ms <= timeMs && acknowledged.has(frame.time_ms))
    .flatMap(frame => frame.observations.map(observation => ({ observation, givenAt: frame.time_ms })))
    .reverse();
  return { request, confirmed, batch: confirmed ? request?.observations ?? [] : [], history };
}
