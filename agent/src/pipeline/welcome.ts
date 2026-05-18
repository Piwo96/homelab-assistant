import type { LoadedSkill } from '../skills/loader';

const GREETING = 'Hi Rolly Mitglied ☺️';
const TAIL = 'Du kannst auch eine Sprachnachricht schicken — ich transkribiere und führe aus.';
const FALLBACK_BODY = 'Ich bin Rolly, dein Homelab-Assistent. Aktuell habe ich keine aktiven Skills — sag mir was du brauchst und ich versuche es.';

/** Assemble the /start welcome message from the example groups each loaded
 *  skill advertises in its SKILL.md frontmatter (`welcome:`). Static — no LLM
 *  round-trip — so the first interaction a new user sees is deterministic.
 *  Groups are emitted in the order skills were loaded, then groups within a
 *  skill in declaration order. */
export function buildWelcomeText(skills: LoadedSkill[]): string {
  const groups = skills.flatMap(s => s.welcomeGroups);
  if (groups.length === 0) {
    return [GREETING, '', FALLBACK_BODY].join('\n');
  }
  const intro = 'Ich bin Rolly, dein Homelab-Assistent. Sag einfach was du brauchst:';
  const lines = groups.map(g => {
    const quoted = g.examples.map(e => `„${e}"`).join(', ');
    return `• ${g.heading}: ${quoted}`;
  });
  return [GREETING, '', intro, '', ...lines, '', TAIL].join('\n');
}
