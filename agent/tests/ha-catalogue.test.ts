import { describe, it, expect } from 'bun:test';
import { startCatalogueRefresh } from '../src/skills/ha-catalogue';
import { mkdtempSync, writeFileSync, chmodSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

/** Make a minimal "skillsRoot/homeassistant/scripts/" tree with a fake
 *  homeassistant_catalogue.py that prints a deterministic counter so we
 *  can observe successive refreshes. */
function makeFakeSkillsRoot(): string {
  const root = mkdtempSync(join(tmpdir(), 'ha-cat-'));
  const scripts = join(root, 'homeassistant', 'scripts');
  mkdirSync(scripts, { recursive: true });
  const counterFile = join(scripts, 'counter.txt');
  writeFileSync(counterFile, '0');
  const script = join(scripts, 'homeassistant_catalogue.py');
  writeFileSync(script, `#!/usr/bin/env python3
from pathlib import Path
p = Path("${counterFile}")
n = int(p.read_text() or "0") + 1
p.write_text(str(n))
print(f"snapshot #{n}")
`);
  chmodSync(script, 0o755);
  return root;
}

describe('startCatalogueRefresh', () => {
  it('invokes onUpdate with each fresh snapshot at the given interval', async () => {
    const root = makeFakeSkillsRoot();
    const snapshots: string[] = [];
    const handle = startCatalogueRefresh(root, 60, (s) => { snapshots.push(s); });

    // Three intervals plus a small buffer for subprocess spawn time.
    await new Promise<void>((res) => setTimeout(res, 250));
    handle.stop();

    // At minimum we expect 2 refreshes (interval 60ms over 250ms). Hard
    // numbers depend on scheduler jitter; assert "≥ 2 and monotonic".
    expect(snapshots.length).toBeGreaterThanOrEqual(2);
    for (let i = 1; i < snapshots.length; i++) {
      const prev = parseInt(snapshots[i - 1]!.match(/#(\d+)/)?.[1] ?? '0', 10);
      const curr = parseInt(snapshots[i]!.match(/#(\d+)/)?.[1] ?? '0', 10);
      expect(curr).toBeGreaterThan(prev);
    }
  });

  it('stop() really stops further refreshes', async () => {
    const root = makeFakeSkillsRoot();
    const snapshots: string[] = [];
    const handle = startCatalogueRefresh(root, 60, (s) => { snapshots.push(s); });
    await new Promise<void>((res) => setTimeout(res, 150));
    handle.stop();
    const afterStopCount = snapshots.length;
    await new Promise<void>((res) => setTimeout(res, 200));
    expect(snapshots.length).toBe(afterStopCount);
  });
});
