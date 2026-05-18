import { mkdir } from 'node:fs/promises';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadEnv } from './config/env';
import { openDb } from './memory/db';
import { loadSkills } from './skills/loader';
import { SkillRegistry } from './skills/registry';
import { isLmStudioReachable } from './llm/health';
import { wakeGamingPc } from './wol/wake';
import { sendText, setMyCommands } from './telegram/send';
import { downloadTelegramFile } from './telegram/download';
import { transcribeAudio } from './llm/transcribe';
import { runSkillCommand } from './skills/executor';
import { createSkillContextCache } from './skills/context-cache';
import { createLlmRouter } from './router/llm-router';
import { buildGenerator } from './llm/generate';
import { lmStudioModel } from './llm/lm-studio';
import { buildWelcomeText } from './pipeline/welcome';
import { startServer } from './server';
import { log } from './utils/logger';

// Default TTL for skill-owned context (entity catalogue etc.). The cache
// keeps the previous value on fetch errors, so a transient HA blip never
// poisons the prompt.
const CONTEXT_TTL_MS = 30 * 60 * 1000;

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../');

function resolveRepoPath(p: string): string {
  if (isAbsolute(p)) return p;
  // Legacy support: values prefixed with `../` were cwd-relative in the old
  // agent/.env.example; treat them as repo-root-relative by stripping the prefix.
  const cleaned = p.replace(/^(\.\.\/)+/, '');
  return resolve(REPO_ROOT, cleaned);
}

async function main(): Promise<void> {
  const env = loadEnv();
  const dataDir = resolveRepoPath(env.DATA_DIR);
  const skillsRoot = resolveRepoPath(env.SKILLS_ROOT);
  await mkdir(dataDir, { recursive: true });
  const db = openDb(join(dataDir, 'agent.db'));

  // smart-home is the user-facing domain layer; the homeassistant skill stays
  // on disk as a standalone CLI but is intentionally not loaded into the bot.
  const skills = await loadSkills(skillsRoot, ['smart-home']);
  if (skills.length === 0) throw new Error('No skills loaded');
  const registry = new SkillRegistry();
  registry.replaceAll(skills);

  const generate = buildGenerator({ baseUrl: env.LM_STUDIO_URL, modelId: env.LM_STUDIO_MODEL });

  // Skill-owned context: each skill with hasContext=true exposes `--json context`,
  // which the cache fetches lazily and refreshes every CONTEXT_TTL_MS.
  const contextCache = createSkillContextCache({
    skills: skills.map(s => ({ id: s.id, hasContext: s.hasContext })),
    fetch: async (skillId) => {
      const skill = skills.find(s => s.id === skillId);
      if (!skill || !skill.scriptPaths[0]) throw new Error(`No script for skill ${skillId}`);
      const t0 = Date.now();
      const res = await runSkillCommand(skill.scriptPaths[0], 'context', {}, { timeoutMs: 15_000 });
      if (!res.success) {
        throw new Error(`context command failed: exit=${res.exitCode} stderr=${res.stderr.slice(0, 200)}`);
      }
      const data = res.data as { markdown?: string } | undefined;
      if (!data || typeof data.markdown !== 'string') {
        throw new Error(`context command returned unexpected shape: ${res.stdout.slice(0, 200)}`);
      }
      log.info('skill_context_fetched', { skillId, ms: Date.now() - t0, chars: data.markdown.length });
      return data.markdown;
    },
    ttlMs: CONTEXT_TTL_MS,
  });
  contextCache.start();

  // Stage-1 LLM router. Only called when >1 skill is loaded (handle-message
  // falls into the fast-path when there's a single skill).
  const llmRouter = createLlmRouter({
    model: lmStudioModel({ baseUrl: env.LM_STUDIO_URL, modelId: env.LM_STUDIO_MODEL }),
  });

  const welcomeText = buildWelcomeText(skills);
  log.info('welcome_built', { chars: welcomeText.length, skillGroups: skills.flatMap(s => s.welcomeGroups).length });

  const handleDeps: import('./pipeline/handle-message').HandleDeps = {
    db,
    registry,
    generate,
    llmRouter,
    contextCache,
    welcomeText,
    healthCheck: () => isLmStudioReachable({ baseUrl: env.LM_STUDIO_URL, timeoutMs: 3000 }),
    wakeGamingPc: () => wakeGamingPc({ skillsRoot, timeoutMs: 270_000 }),
    notifyStatus: async (chatId, text) => {
      await sendText({ botToken: env.TELEGRAM_BOT_TOKEN }, chatId, text);
    },
    transcribeVoice: async (fileId) => {
      const audio = await downloadTelegramFile({ botToken: env.TELEGRAM_BOT_TOKEN }, fileId);
      return transcribeAudio(
        { baseUrl: env.LM_STUDIO_URL, model: env.WHISPER_MODEL },
        { data: audio.data, filename: audio.filename, mimeType: audio.mimeType },
      );
    },
  };

  // Register the slash-menu /commands. Idempotent (Telegram replaces the
  // existing list on each call), so safe to run on every bootstrap.
  // Best-effort: a transient Telegram-API blip shouldn't block startup.
  setMyCommands(
    { botToken: env.TELEGRAM_BOT_TOKEN },
    [{ command: 'start', description: 'Rolly begrüßen und Beispiele anzeigen' }],
  ).catch(err => log.warn('set_my_commands_failed', { err: String(err) }));

  startServer({ env, db, handleDeps });
}

main().catch(err => {
  log.error('startup_failed', { err: String(err) });
  process.exit(1);
});
