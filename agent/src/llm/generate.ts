import { generateText } from 'ai';
import { lmStudioModel, type LmStudioConfig } from './lm-studio';
import type { GenerateInput, GenerateOutput } from '../pipeline/handle-message';
import { log } from '../utils/logger';

const MAX_STEPS = 5;
// Output-token headroom per LLM call. Gemma-4B in thinking mode spends a chunk
// of its output budget on reasoning before producing the user-facing text; the
// AI-SDK default (~1024) was getting truncated for tool-heavy responses (e.g.
// listing lights across two areas), surfacing as empty text + finishReason='length'.
const MAX_OUTPUT_TOKENS = 16384;

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
      maxTokens: MAX_OUTPUT_TOKENS,
      experimental_providerMetadata: {
        'lm-studio': {
          reasoning: { effort: input.reasoningEffort },
        },
      },
      onStepFinish: ({ stepType, toolCalls, text, finishReason }) => {
        log.info('llm_step', {
          stepType,
          finishReason,
          textLen: text?.length ?? 0,
          toolCalls: toolCalls?.map(tc => ({ name: tc.toolName, args: tc.args })) ?? [],
        });
      },
    });
    // Aggregate tool calls across all steps (result.toolCalls only holds the last step's calls).
    const allToolCalls = result.steps?.flatMap(s => s.toolCalls ?? []) ?? result.toolCalls ?? [];
    return {
      text: result.text,
      toolCalls: allToolCalls.map(tc => ({ toolName: tc.toolName, args: tc.args })),
      finishReason: result.finishReason,
    };
  };
}
