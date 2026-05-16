export interface EmbedOptions {
  baseUrl: string;
  model: string;
}

export async function embed(text: string, opts: EmbedOptions): Promise<number[]> {
  const res = await fetch(`${opts.baseUrl}/v1/embeddings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: opts.model, input: text }),
  });
  if (!res.ok) {
    throw new Error(`Embedding request failed: ${res.status} ${await res.text()}`);
  }
  const json = await res.json() as { data: Array<{ embedding: number[] }> };
  const vec = json.data[0]?.embedding;
  if (!vec) throw new Error('Embedding response missing data[0].embedding');
  return vec;
}

export async function embedMany(texts: string[], opts: EmbedOptions): Promise<number[][]> {
  return Promise.all(texts.map(t => embed(t, opts)));
}
