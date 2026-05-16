import { createOpenAICompatible } from '@ai-sdk/openai-compatible';
import type { LanguageModelV1 } from 'ai';
import { writeFileSync } from 'node:fs';

export interface LmStudioConfig {
  baseUrl: string;
  modelId: string;
}

// Optional diagnostic fetch: when DUMP_LLM_REQUEST=1, writes the outgoing
// request body to /tmp/llm-request.json so we can inspect exactly what the
// AI SDK serializes to LM Studio. No-op in normal operation.
const debugFetch: typeof fetch = async (input, init) => {
  if (process.env.DUMP_LLM_REQUEST === '1' && init?.body) {
    try {
      const body = typeof init.body === 'string' ? init.body : '<non-string>';
      writeFileSync('/tmp/llm-request.json', body);
    } catch {
      // best-effort diagnostic; ignore failures
    }
  }
  return fetch(input, init);
};

export function lmStudioModel(config: LmStudioConfig): LanguageModelV1 {
  const provider = createOpenAICompatible({
    name: 'lm-studio',
    baseURL: `${config.baseUrl}/v1`,
    fetch: debugFetch,
  });
  return provider(config.modelId);
}
