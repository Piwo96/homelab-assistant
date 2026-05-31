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
  // Outer bound must exceed the python WOL_TIMEOUT (default 360s) so we don't
  // SIGKILL the wait mid-boot; a cold start incl. LM Studio model load is slow.
  const timeoutMs = opts.timeoutMs ?? 390_000;
  const start = Date.now();

  // NB: the wol skill's `wake` subcommand only accepts `--wait`; it always emits
  // JSON on stdout. Passing a `--json` flag here makes argparse exit(2) with
  // "unrecognized arguments" *before any magic packet is sent*, so every wake
  // silently failed. Do not re-add it.
  const proc = Bun.spawn({
    cmd: ['python', scriptPath, 'wake', '--wait'],
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
  // Parse JSON output. With `--wait`, the script nests the readiness result under
  // `lm_studio.available` (NOT a top-level `lm_studio_available`). A sent packet
  // returns success:true even if LM Studio never answered, so we must inspect the
  // nested flag — otherwise a wake where the PC powered on but LM Studio timed out
  // would be reported as success and we'd proceed into a failing generate call.
  let success = true;
  try {
    const j = JSON.parse(stdout) as { lm_studio?: { available?: boolean }; success?: boolean };
    // We always pass --wait, so the script must report lm_studio.available === true.
    // Treat a missing/non-true field as failure (safe default): better to say "kommt
    // nicht hoch" than to proceed into a generate call that hits ECONNREFUSED.
    if (j.success === false || j.lm_studio?.available !== true) success = false;
  } catch {
    // Non-JSON output — fall back to exit code, which was 0, so consider success.
  }
  return { success, ms };
}
