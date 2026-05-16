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
  it('rejects invalid args via Zod before exec', async () => {
    const skillTool: SkillTool = {
      name: 'echo__turn-on',
      scriptPath: makeEchoScript(),
      command: 'turn-on',
      description: 'turn on',
      schema: z.object({ entity_id: z.string(), brightness: z.number().int().optional() }),
      isWrite: true,
    };
    const tool = defineSkillTool(skillTool, { positionalArgs: ['entity_id'] });
    await expect(tool.execute({ brightness: 100 } as never, {} as never)).rejects.toThrow();
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
