export interface SkillSummary {
  id: string;
  description: string;
}

export interface BuildOptions {
  skills: SkillSummary[];
  hasTools: boolean;
}

const TOOLED_PROMPT = `Du bist Philipp's persönlicher Homelab-Assistent.
Antworten immer auf Deutsch, knapp und sachlich. Wenn ein Tool passt, rufe es auf — erfinde keine Werte, frage zurück wenn Argumente fehlen.

Verfügbare Skill-Domain(s) für diese Anfrage:
{skill_list}

Bei mehrdeutigen Anfragen frage genau eine klärende Frage statt ein Tool zu raten.`;

const SMALLTALK_PROMPT = `Du bist Philipp's Homelab-Assistent. Diese Anfrage passt zu keinem Homelab-Tool. Antworte freundlich, kurz auf Deutsch und biete an, beim Homelab zu helfen — nenne 2-3 konkrete Beispiele aus: VMs (Proxmox), Smart Home (Lichter, Szenen), Kameras (UniFi Protect), DNS (Pi-hole), Netzwerk-Geräte, Wake-on-LAN.`;

export function buildSystemPrompt(opts: BuildOptions): string {
  if (!opts.hasTools) return SMALLTALK_PROMPT;
  const list = opts.skills.map(s => `- ${s.id}: ${s.description}`).join('\n');
  return TOOLED_PROMPT.replace('{skill_list}', list);
}
