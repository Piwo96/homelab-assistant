import { readdir, readFile, stat } from 'node:fs/promises';
import { join, basename, dirname } from 'node:path';
import matter from 'gray-matter';
import { commandToZod, type HelpJsonScript } from '../tools/help-json-to-zod';
import type { ZodObject, ZodTypeAny } from 'zod';
import { log } from '../utils/logger';

export interface SkillTool {
  name: string;                    // e.g. "homeassistant__turn-on"
  scriptPath: string;
  command: string;                 // e.g. "turn-on"
  description: string;
  schema: ZodObject<Record<string, ZodTypeAny>>;
  isWrite: boolean;
  /** Args that argparse expects positionally (no `--flag`). The executor
   *  passes these in declaration order; everything else becomes `--flag value`.
   *  Populated from the `positional` field in --help-json output. Without
   *  this list, required-but-optional flags like `--tilt-position` would be
   *  passed positionally and argparse would error with "the following arguments
   *  are required: --tilt-position". */
  positionalArgs: string[];
}

export interface LoadedSkill {
  id: string;
  description: string;
  triggers: string[];
  intentHints: string[];
  scriptPaths: string[];
  tools: SkillTool[];
}

interface Frontmatter {
  name?: string;
  description?: string;
  triggers?: string[];
  intent_hints?: string[];
}

async function listScriptFiles(dir: string): Promise<string[]> {
  try {
    const entries = await readdir(dir);
    return entries
      .filter(e => e.endsWith('_api.py'))
      .map(e => join(dir, e))
      .sort();
  } catch {
    return [];
  }
}

async function fetchHelpJson(scriptPath: string): Promise<HelpJsonScript> {
  const proc = Bun.spawn({
    cmd: [process.env.PYTHON_BIN || 'python3', scriptPath, '--help-json'],
    stdout: 'pipe',
    stderr: 'pipe',
    cwd: dirname(scriptPath),
  });
  const [stdout, stderr, code] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited,
  ]);
  if (code !== 0) {
    throw new Error(`--help-json failed (exit ${code}) for ${scriptPath}: ${stderr}`);
  }
  return JSON.parse(stdout) as HelpJsonScript;
}

function scriptStem(scriptPath: string): string {
  return basename(scriptPath).replace(/_api\.py$/, '');
}

export async function loadSkills(skillsRoot: string, only?: string[]): Promise<LoadedSkill[]> {
  const entries = await readdir(skillsRoot);
  const result: LoadedSkill[] = [];
  for (const name of entries) {
    if (only && !only.includes(name)) continue;
    const skillDir = join(skillsRoot, name);
    const skillMdPath = join(skillDir, 'SKILL.md');
    let frontmatter: Frontmatter = {};
    try {
      const md = await readFile(skillMdPath, 'utf8');
      frontmatter = matter(md).data as Frontmatter;
    } catch {
      continue; // not a skill dir
    }
    const scriptDir = join(skillDir, 'scripts');
    try {
      await stat(scriptDir);
    } catch {
      continue;
    }
    const scriptPaths = await listScriptFiles(scriptDir);
    if (scriptPaths.length === 0) continue;

    const tools: SkillTool[] = [];
    for (const scriptPath of scriptPaths) {
      let helpJson: HelpJsonScript;
      try {
        helpJson = await fetchHelpJson(scriptPath);
      } catch (err) {
        log.warn('skill_load_help_json_failed', { scriptPath, err: String(err) });
        continue;
      }
      const stem = scriptStem(scriptPath);
      for (const [cmdName, cmd] of Object.entries(helpJson.commands)) {
        const positionalArgs = cmd.args.filter(a => a.positional).map(a => a.name);
        tools.push({
          name: `${stem}__${cmdName}`,
          scriptPath,
          command: cmdName,
          description: cmd.description || cmdName,
          schema: commandToZod(cmd),
          isWrite: cmd.is_write,
          positionalArgs,
        });
      }
    }

    result.push({
      id: frontmatter.name ?? name,
      description: frontmatter.description ?? '',
      triggers: frontmatter.triggers ?? [],
      intentHints: frontmatter.intent_hints ?? [],
      scriptPaths,
      tools,
    });
  }
  return result;
}
