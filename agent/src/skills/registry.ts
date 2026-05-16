import type { LoadedSkill, SkillTool } from './loader';

export class SkillRegistry {
  private skills: LoadedSkill[] = [];

  replaceAll(skills: LoadedSkill[]): void {
    this.skills = skills;
  }

  all(): LoadedSkill[] {
    return [...this.skills];
  }

  byId(id: string): LoadedSkill | undefined {
    return this.skills.find(s => s.id === id);
  }

  toolsForSkillIds(ids: string[]): SkillTool[] {
    return this.skills
      .filter(s => ids.includes(s.id))
      .flatMap(s => s.tools);
  }
}
