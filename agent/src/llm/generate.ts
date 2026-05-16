import { generateText } from 'ai';
import { lmStudioModel, type LmStudioConfig } from './lm-studio';
import type { GenerateInput, GenerateOutput } from '../pipeline/handle-message';

const MAX_STEPS = 5;

export function buildGenerator(cfg: LmStudioConfig) {
  const model = lmStudioModel(cfg);
  return async function generate(input: GenerateInput): Promise<GenerateOutput> {
    const result = await generateText({
      model,
      system: input.system,
      messages: input.messages.map(m => ({ role: m.role, content: m.content })),
      tools: input.tools,
      toolChoice: Object.keys(input.tools).length > 0 ? 'auto' : 'none',
      maxSteps: MAX_STEPS,
      experimental_providerMetadata: {
        'lm-studio': {
          reasoning: { effort: input.reasoningEffort },
        },
      },
    });
    return {
      text: result.text,
      toolCalls: result.toolCalls?.map(tc => ({ toolName: tc.toolName, args: tc.args })) ?? [],
    };
  };
}
