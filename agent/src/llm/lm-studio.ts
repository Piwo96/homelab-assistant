import { createOpenAICompatible } from '@ai-sdk/openai-compatible';
import type { LanguageModelV1 } from 'ai';

export interface LmStudioConfig {
  baseUrl: string;
  modelId: string;
}

export function lmStudioModel(config: LmStudioConfig): LanguageModelV1 {
  const provider = createOpenAICompatible({
    name: 'lm-studio',
    baseURL: `${config.baseUrl}/v1`,
  });
  return provider(config.modelId);
}
