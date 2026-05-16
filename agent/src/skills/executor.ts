export interface ExecResult {
  success: boolean;
  data?: unknown;
  stdout: string;
  stderr: string;
  exitCode: number;
  timedOut?: boolean;
}

export interface ExecOptions {
  timeoutMs?: number;
}

function argsToFlags(args: Record<string, unknown>): string[] {
  const out: string[] = [];
  for (const [k, v] of Object.entries(args)) {
    if (v === undefined || v === null) continue;
    const flag = `--${k.replace(/_/g, '-')}`;
    if (typeof v === 'boolean') {
      if (v) out.push(flag);
    } else if (Array.isArray(v)) {
      out.push(flag, ...v.map(String));
    } else {
      out.push(flag, String(v));
    }
  }
  return out;
}

function buildArgv(
  command: string,
  args: Record<string, unknown>,
  positionalArgs: string[] = [],
): string[] {
  const positional: string[] = [];
  const remaining: Record<string, unknown> = { ...args };
  for (const name of positionalArgs) {
    if (name in remaining) {
      const v = remaining[name];
      if (v !== undefined && v !== null) positional.push(String(v));
      delete remaining[name];
    }
  }
  return ['--json', command, ...positional, ...argsToFlags(remaining)];
}

export async function runSkillCommand(
  scriptPath: string,
  command: string,
  args: Record<string, unknown>,
  options: ExecOptions = {},
  positionalArgs: string[] = [],
): Promise<ExecResult> {
  const timeoutMs = options.timeoutMs ?? 30_000;
  const argv = buildArgv(command, args, positionalArgs);
  const proc = Bun.spawn({
    cmd: [process.env.PYTHON_BIN || 'python3', scriptPath, ...argv],
    stdout: 'pipe',
    stderr: 'pipe',
  });
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    proc.kill('SIGKILL');
  }, timeoutMs);
  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited,
  ]);
  clearTimeout(timer);
  if (timedOut) {
    return { success: false, stdout, stderr, exitCode: -1, timedOut: true };
  }
  if (exitCode !== 0) {
    return { success: false, stdout, stderr, exitCode };
  }
  let data: unknown = undefined;
  if (stdout.trim()) {
    try {
      data = JSON.parse(stdout);
    } catch {
      data = stdout;
    }
  }
  return { success: true, data, stdout, stderr, exitCode };
}
