import { describe, it, expect } from 'bun:test';
import { runSkillCommand } from '../src/skills/executor';
import { writeFileSync, chmodSync, mkdtempSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

function makeFakeScript(body: string): string {
  const dir = mkdtempSync(join(tmpdir(), 'exec-'));
  const p = join(dir, 'fake_api.py');
  writeFileSync(p, `#!/usr/bin/env python3\nimport sys, json\n${body}\n`);
  chmodSync(p, 0o755);
  return p;
}

describe('runSkillCommand', () => {
  it('parses JSON stdout from a successful command', async () => {
    const script = makeFakeScript(`print(json.dumps({"ok": True, "value": 42}))`);
    const out = await runSkillCommand(script, 'noop', {});
    expect(out.success).toBe(true);
    expect(out.data).toEqual({ ok: true, value: 42 });
  });

  it('returns error when subprocess exits non-zero', async () => {
    const script = makeFakeScript(`print("fail", file=sys.stderr); sys.exit(2)`);
    const out = await runSkillCommand(script, 'broken', {});
    expect(out.success).toBe(false);
    expect(out.exitCode).toBe(2);
    expect(out.stderr).toContain('fail');
  });

  it('passes positional + flag args correctly', async () => {
    const script = makeFakeScript(
      `import argparse; p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="cmd"); ` +
      `t=sub.add_parser("t"); t.add_argument("entity_id"); t.add_argument("--brightness", type=int); ` +
      `p.add_argument("--json", action="store_true"); a=p.parse_args(); ` +
      `print(json.dumps({"entity_id": a.entity_id, "brightness": a.brightness}))`,
    );
    const out = await runSkillCommand(
      script,
      't',
      { entity_id: 'light.kitchen', brightness: 200 },
      {},
      ['entity_id'],
    );
    expect(out.success).toBe(true);
    expect(out.data).toEqual({ entity_id: 'light.kitchen', brightness: 200 });
  });

  it('times out long-running subprocesses', async () => {
    const script = makeFakeScript(`import time; time.sleep(60)`);
    const out = await runSkillCommand(script, 'sleep', {}, { timeoutMs: 200 });
    expect(out.success).toBe(false);
    expect(out.timedOut).toBe(true);
  });
});
