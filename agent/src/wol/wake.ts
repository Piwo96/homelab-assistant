/**
 * Wake-on-LAN wrapper around the wol skill's python CLI.
 *
 * Runs `python <skillsRoot>/wol/scripts/wol_api.py wake --wait --json` which
 * sends the magic packet and then polls LM Studio's endpoint until it answers
 * (or until WOL_TIMEOUT seconds elapse — default 120). We just shell out so the
 * agent reuses the user's already-configured WoL credentials and broadcast
 * resolution from `.env`.
 */

import { join } from 'node:path';
import { log } from '../utils/logger';

export interface WakeResult {
  success: boolean;
  ms: number;
  stderr?: string;
}

export interface WakeOptions {
  skillsRoot: string;
  /** Hard cap on total wake time. The python script also enforces its own
   *  WOL_TIMEOUT; this is a defensive outer bound. */
  timeoutMs?: number;
}

export async function wakeGamingPc(opts: WakeOptions): Promise<WakeResult> {
  const scriptPath = join(opts.skillsRoot, 'wol', 'scripts', 'wol_api.py');
  const timeoutMs = opts.timeoutMs ?? 270_000;
  const start = Date.now();

  const proc = Bun.spawn({
    cmd: ['python', scriptPath, 'wake', '--wait', '--json'],
    stdout: 'pipe',
    stderr: 'pipe',
  });

  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; proc.kill('SIGKILL'); }, timeoutMs);

  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited,
  ]);
  clearTimeout(timer);

  const ms = Date.now() - start;
  if (timedOut) {
    log.warn('wol_timeout', { ms, stderr: stderr.trim() });
    return { success: false, ms, stderr: 'wake script timed out' };
  }
  if (exitCode !== 0) {
    log.warn('wol_exit_nonzero', { exitCode, stderr: stderr.trim() });
    return { success: false, ms, stderr: stderr.trim() };
  }
  // Parse JSON output; the python script reports lm_studio_available when --wait succeeds.
  let success = true;
  try {
    const j = JSON.parse(stdout) as { lm_studio_available?: boolean; success?: boolean };
    if (j.lm_studio_available === false || j.success === false) success = false;
  } catch {
    // Non-JSON output — fall back to exit code, which was 0, so consider success.
  }
  return { success, ms };
}
