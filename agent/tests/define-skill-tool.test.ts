import { describe, it, expect } from 'bun:test';
import { z } from 'zod';
import { defineSkillTool } from '../src/tools/define-skill-tool';
import type { SkillTool } from '../src/skills/loader';
import { writeFileSync, chmodSync, mkdtempSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

function makeEchoScript(): string {
  const dir = mkdtempSync(join(tmpdir(), 'echo-'));
  const p = join(dir, 'echo_api.py');
  writeFileSync(p, `#!/usr/bin/env python3
import argparse, json, sys
p = argparse.ArgumentParser()
p.add_argument("--json", action="store_true")
sub = p.add_subparsers(dest="cmd")
t = sub.add_parser("turn-on"); t.add_argument("entity_id"); t.add_argument("--brightness", type=int)
a = p.parse_args()
print(json.dumps({"called": a.cmd, "id": a.entity_id, "b": a.brightness}))
`);
  chmodSync(p, 0o755);
  return p;
}

describe('defineSkillTool', () => {
  it('returns structured error when subprocess argparse rejects missing args', async () => {
    const skillTool: SkillTool = {
      name: 'echo__turn-on',
      scriptPath: makeEchoScript(),
      command: 'turn-on',
      description: 'turn on',
      schema: z.object({ entity_id: z.string(), brightness: z.number().int().optional() }),
      isWrite: true,
    };
    const tool = defineSkillTool(skillTool, { positionalArgs: ['entity_id'] });
    const result = await tool.execute({ brightness: 100 } as never, {} as never) as { ok: boolean; error: string };
    expect(result.ok).toBe(false);
    expect(result.error.toLowerCase()).toContain('entity_id');
  });

  it('returns structured {ok:false, error} on subprocess failure (does not throw)', async () => {
    // Build a script that always exits 1 with a Python-style traceback so we
    // can verify the error summary extraction picks the final RuntimeError line.
    const dir = mkdtempSync(join(tmpdir(), 'fail-'));
    const p = join(dir, 'fail_api.py');
    writeFileSync(p, `#!/usr/bin/env python3
import sys
sys.stderr.write("""Traceback (most recent call last):
  File "fail_api.py", line 1, in <module>
    raise RuntimeError("Not found: /states/light.buero")
RuntimeError: Not found: /states/light.buero
""")
sys.exit(1)
`);
    chmodSync(p, 0o755);

    const skillTool: SkillTool = {
      name: 'fail__do',
      scriptPath: p,
      command: 'do',
      description: 'fails',
      schema: z.object({ entity_id: z.string() }),
      isWrite: false,
    };
    const tool = defineSkillTool(skillTool, { positionalArgs: ['entity_id'] });
    const result = await tool.execute({ entity_id: 'light.buero' } as never, {} as never) as { ok: boolean; error: string; tool: string };
    expect(result.ok).toBe(false);
    expect(result.error).toBe('RuntimeError: Not found: /states/light.buero');
    expect(result.tool).toBe('fail__do');
  });

  it('runs subprocess and returns parsed JSON on valid args', async () => {
    const skillTool: SkillTool = {
      name: 'echo__turn-on',
      scriptPath: makeEchoScript(),
      command: 'turn-on',
      description: 'turn on',
      schema: z.object({ entity_id: z.string(), brightness: z.number().int().optional() }),
      isWrite: true,
    };
    const tool = defineSkillTool(skillTool, { positionalArgs: ['entity_id'] });
    const result = await tool.execute({ entity_id: 'light.kitchen', brightness: 200 } as never, {} as never);
    expect(result).toEqual({ called: 'turn-on', id: 'light.kitchen', b: 200 });
  });
});
