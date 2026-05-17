import { describe, it, expect } from 'bun:test';
import { loadSkills } from '../src/skills/loader';
import { resolve } from 'node:path';

const SKILLS_ROOT = resolve(import.meta.dir, '../../.claude/skills');

describe('loadSkills', () => {
  it('loads homeassistant skill with both scripts', async () => {
    const skills = await loadSkills(SKILLS_ROOT, ['homeassistant']);
    expect(skills).toHaveLength(1);
    const ha = skills[0]!;
    expect(ha.id).toBe('homeassistant');
    expect(ha.description).toContain('Smart Home');
    expect(ha.tools.length).toBeGreaterThan(5);
    const turnOn = ha.tools.find(t => t.name === 'homeassistant__turn-on');
    expect(turnOn).toBeDefined();
    expect(turnOn?.isWrite).toBe(true);
    expect(turnOn?.scriptPath).toMatch(/homeassistant_api\.py$/);
    const dashboardGet = ha.tools.find(t => t.name === 'dashboard__get');
    expect(dashboardGet).toBeDefined();
    expect(dashboardGet?.isWrite).toBe(false);
  });

  it('skips skills with no *_api.py scripts', async () => {
    const skills = await loadSkills(SKILLS_ROOT, ['homelab']);
    expect(skills).toHaveLength(0);
  });

  it('sets hasContext=true when --help-json includes context command and filters it from tools', async () => {
    const skills = await loadSkills(`${import.meta.dir}/../../.claude/skills`, ['smart-home']);
    expect(skills).toHaveLength(1);
    const smartHome = skills[0]!;
    expect(smartHome.hasContext).toBe(true);
    const toolNames = smartHome.tools.map(t => t.name);
    expect(toolNames).not.toContain('smart-home__context');
  });
});
