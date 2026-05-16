export interface RoutableSkill {
  id: string;
  embedding: number[];
}

export type Band = 'high' | 'med' | 'low';

export interface Thresholds {
  high: number;
  med: number;
}

export interface RouteResult {
  band: Band;
  selectedIds: string[];
  scores: Array<{ id: string; score: number }>;
}

export function cosine(a: number[], b: number[]): number {
  if (a.length !== b.length || a.length === 0) return 0;
  let dot = 0, na = 0, nb = 0;
  for (let i = 0; i < a.length; i++) {
    const ai = a[i] ?? 0;
    const bi = b[i] ?? 0;
    dot += ai * bi;
    na += ai * ai;
    nb += bi * bi;
  }
  const denom = Math.sqrt(na) * Math.sqrt(nb);
  if (denom === 0) return 0;
  return dot / denom;
}

function dot(a: number[], b: number[]): number {
  const n = Math.min(a.length, b.length);
  let sum = 0;
  for (let i = 0; i < n; i++) {
    sum += (a[i] ?? 0) * (b[i] ?? 0);
  }
  return sum;
}

export function route(query: number[], skills: RoutableSkill[], thresholds: Thresholds): RouteResult {
  // Uses dot product; assumes query and skill embeddings are unit-normalized
  // (real embeddings from LM Studio are L2-normalized). For unit vectors,
  // dot product equals cosine similarity.
  const scored = skills
    .map(s => ({ id: s.id, score: dot(query, s.embedding) }))
    .sort((a, b) => b.score - a.score);

  const top = scored[0];
  if (!top) return { band: 'low', selectedIds: [], scores: [] };

  if (top.score >= thresholds.high) {
    return { band: 'high', selectedIds: [top.id], scores: scored };
  }
  if (top.score >= thresholds.med) {
    return { band: 'med', selectedIds: scored.slice(0, 2).map(s => s.id), scores: scored };
  }
  return { band: 'low', selectedIds: [], scores: scored };
}
