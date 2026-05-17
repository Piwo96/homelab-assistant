import { generateText, type LanguageModel } from 'ai';
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

Anfrage: "${input.msg}"

Antwort als JSON (keine Erklärung, kein Markdown):
{ "skill": "<name>" }  ODER  { "skill": null }`;
}

/** Strip ```json fences, find the first balanced {...} block, parse, validate. */
export function parseRouterResponse(raw: string, candidates: string[]): RouterResult | null {
  const stripped = raw.replace(/```(?:json)?/gi, '').trim();
  const firstBrace = stripped.indexOf('{');
  if (firstBrace < 0) return null;
  for (let end = stripped.length; end > firstBrace; end--) {
    const slice = stripped.slice(firstBrace, end);
    if (!slice.endsWith('}')) continue;
    try {
      const parsed = JSON.parse(slice) as { skill?: unknown };
      const skill = parsed?.skill;
      if (skill === null) return null;
      if (typeof skill === 'string' && candidates.includes(skill)) {
        return { skillId: skill };
      }
      return null; // unknown / wrong type
    } catch {
      // try a shorter window
    }
  }
  return null;
}

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
      const t0 = Date.now();
      try {
        const { text } = await generateText({
          model: deps.model,
          prompt,
          temperature: 0,
          maxTokens: 50,
        });
        const result = parseRouterResponse(text, input.candidates.map(c => c.id));
        log.info('llm_router_decision', { ms: Date.now() - t0, result: result?.skillId ?? null, textLen: text.length });
        return result;
      } catch (err) {
        log.warn('llm_router_call_failed', { err: String(err) });
        return null;
      }
    },
  };
}
