import { generateObject, NoObjectGeneratedError, type LanguageModel } from 'ai';
import { z } from 'zod';
import { log } from '../utils/logger';

export interface RouterCandidate {
  id: string;
  description: string;
}

export interface RouterInput {
  msg: string;
  recentMessages: Array<{ role: 'user' | 'assistant'; content: string }>;
  candidates: RouterCandidate[];
}

export interface RouterResult {
  skillId: string;
}

export function buildRouterPrompt(input: RouterInput): string {
  const list = input.candidates.map(c => `- ${c.id}: ${c.description}`).join('\n');
  const recent = input.recentMessages
    .slice(-3)
    .map(m => `[${m.role}] ${m.content}`)
    .join('\n') || '(keine)';
  return `Du bist ein Skill-Router für einen Homelab-Assistenten. Wähle den passenden Skill für die User-Anfrage, oder null wenn keine Domain passt (Smalltalk, Frage außerhalb des Homelabs).

Skills:
${list}

Letzte Nachrichten (Kontext):
${recent}

Anfrage: "${input.msg}"`;
}

const routerSchema = z.object({
  skill: z
    .string()
    .nullable()
    .describe('Skill-ID aus der Skills-Liste oder null bei Smalltalk / außerhalb des Homelabs'),
});

export interface LlmRouterDeps {
  model: LanguageModel;
}

export interface LlmRouter {
  pick(input: RouterInput): Promise<RouterResult | null>;
}

export function createLlmRouter(deps: LlmRouterDeps): LlmRouter {
  return {
    async pick(input: RouterInput): Promise<RouterResult | null> {
      const prompt = buildRouterPrompt(input);
      const validIds = new Set(input.candidates.map(c => c.id));
      const t0 = Date.now();
      try {
        const { object } = await generateObject({
          model: deps.model,
          prompt,
          schema: routerSchema,
          mode: 'json',
          temperature: 0,
          maxTokens: 200,
        });
        const skill = object.skill;
        if (typeof skill === 'string' && validIds.has(skill)) {
          log.info('llm_router_decision', { ms: Date.now() - t0, result: skill });
          return { skillId: skill };
        }
        log.info('llm_router_decision', { ms: Date.now() - t0, result: null, returned: skill });
        return null;
      } catch (err) {
        if (NoObjectGeneratedError.isInstance(err)) {
          // Schema violation / no parseable JSON — treat as "no skill picked"
          // (smalltalk fallback). The model produced output, just not valid.
          log.warn('llm_router_no_object_generated', { err: String(err) });
          return null;
        }
        // Network / HTTP / retry-exhausted / unknown — propagate so the
        // pipeline's outer error handler surfaces a real error to the user
        // instead of silently routing to smalltalk.
        log.error('llm_router_call_failed', { err: String(err) });
        throw err;
      }
    },
  };
}
