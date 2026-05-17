import { tool, type Tool, type ToolExecutionOptions } from 'ai';
import type { SkillTool } from '../skills/loader';
import { runSkillCommand } from '../skills/executor';
import { log } from '../utils/logger';

export interface DefineOptions {
  positionalArgs?: string[];
  timeoutMs?: number;
}

export type SkillToolHandle = Tool & {
  execute: (args: unknown, options: ToolExecutionOptions) => Promise<unknown>;
};

/** Pull the most useful single-line summary out of a stderr blob.
 *  Python tracebacks end with "ErrorType: message" — that's the bit the model
 *  needs to reason about. Everything above is noise that just eats tokens. */
function extractErrorSummary(stderr: string, timedOut: boolean | undefined): string {
  if (timedOut) return 'timed out';
  const trimmed = stderr.trim();
  if (!trimmed) return 'unknown error';
  const lines = trimmed.split('\n').map(l => l.trim()).filter(Boolean);
  // Walk from the end and grab the first "Foo(Error|Exception): bar" line.
  for (let i = lines.length - 1; i >= 0; i--) {
    if (/^[A-Z][A-Za-z]+(Error|Exception):\s/.test(lines[i]!)) return lines[i]!;
  }
  return lines[lines.length - 1] ?? trimmed;
}

export function defineSkillTool(skillTool: SkillTool, opts: DefineOptions = {}): SkillToolHandle {
  const built = tool({
    description: skillTool.description,
    parameters: skillTool.schema,
    execute: async (args) => {
      const result = await runSkillCommand(
        skillTool.scriptPath,
        skillTool.command,
        args as Record<string, unknown>,
        { ...(opts.timeoutMs !== undefined ? { timeoutMs: opts.timeoutMs } : {}) },
        opts.positionalArgs ?? [],
      );
      if (!result.success) {
        const summary = extractErrorSummary(result.stderr, result.timedOut);
        log.warn('skill_tool_failed', { tool: skillTool.name, exitCode: result.exitCode, summary, stderr: result.stderr });
        // Return as a structured tool result instead of throwing. The AI SDK
        // feeds this back to the model as the tool's output, so the model can
        // apologize / ask / try a different entity rather than the whole
        // pipeline failing with "etwas schiefgegangen" at the user.
        return {
          ok: false,
          error: summary,
          tool: skillTool.name,
          exit_code: result.exitCode,
          ...(result.timedOut ? { timed_out: true } : {}),
        };
      }
      return result.data ?? { ok: true };
    },
  });
  return built as unknown as SkillToolHandle;
}

/** @deprecated Use `skillTool.positionalArgs` directly — it comes from
 *  argparse's actual `positional` flag via the help-json. The Zod-shape
 *  inference here treats every required arg as positional, which is wrong
 *  for argparse subcommands that have BOTH a positional + required-but-flag
 *  arg (e.g. cover-set-tilt: positional entity_id + required --tilt-position). */
export function inferPositionals(skillTool: SkillTool): string[] {
  if (skillTool.positionalArgs) return skillTool.positionalArgs;
  // Legacy fallback for callers/tests that build a SkillTool without the field.
  const shape = skillTool.schema.shape;
  const required: string[] = [];
  for (const [key, val] of Object.entries(shape)) {
    if (!val.isOptional()) required.push(key);
  }
  return required;
}
