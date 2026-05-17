import { join } from 'node:path';
import { log } from '../utils/logger';

/**
 * Run the homeassistant_catalogue.py helper at startup to capture a snapshot
 * of every controllable entity grouped by area, in Markdown. The agent
 * injects that snapshot into the LLM's system prompt so the model never
 * has to guess entity_ids — eliminating a whole class of hallucinations
 * ("light.buero", "light.eg_essen_wandleuchten", …).
 *
 * Failure is non-fatal: if HA is unreachable at startup, we log and return
 * undefined; the system prompt falls back to its baseline (no catalogue).
 */
export async function fetchHaCatalogue(skillsRoot: string, timeoutMs = 15_000): Promise<string | undefined> {
  const scriptPath = join(skillsRoot, 'homeassistant', 'scripts', 'homeassistant_catalogue.py');
  const t0 = Date.now();
  try {
    const proc = Bun.spawn({
      cmd: [process.env.PYTHON_BIN || 'python3', scriptPath],
      stdout: 'pipe',
      stderr: 'pipe',
      cwd: join(skillsRoot, 'homeassistant', 'scripts'),
    });
    const timer = setTimeout(() => proc.kill(), timeoutMs);
    const [stdout, stderr, code] = await Promise.all([
      new Response(proc.stdout).text(),
      new Response(proc.stderr).text(),
      proc.exited,
    ]);
    clearTimeout(timer);
    if (code !== 0) {
      log.warn('ha_catalogue_failed', { exitCode: code, stderr: stderr.slice(0, 500) });
      return undefined;
    }
    const text = stdout.trim();
    if (!text) {
      log.warn('ha_catalogue_empty');
      return undefined;
    }
    log.info('ha_catalogue_loaded', { ms: Date.now() - t0, chars: text.length, lines: text.split('\n').length });
    return text;
  } catch (err) {
    log.warn('ha_catalogue_error', { err: String(err) });
    return undefined;
  }
}
