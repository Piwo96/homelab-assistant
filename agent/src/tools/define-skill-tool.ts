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
        log.warn('skill_tool_failed', { tool: skillTool.name, exitCode: result.exitCode, stderr: result.stderr });
        throw new Error(
          `Skill ${skillTool.name} failed (exit ${result.exitCode})${result.timedOut ? ' [timeout]' : ''}: ${result.stderr.trim() || 'unknown'}`,
        );
      }
      return result.data ?? { ok: true };
    },
  });
  return built as unknown as SkillToolHandle;
}

export function inferPositionals(skillTool: SkillTool): string[] {
  const shape = skillTool.schema.shape;
  const required: string[] = [];
  for (const [key, val] of Object.entries(shape)) {
    if (!val.isOptional()) required.push(key);
  }
  return required;
}
