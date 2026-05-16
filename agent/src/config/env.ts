import { z } from 'zod';

const csvNumbers = z.string().transform((s, ctx) => {
  const parts = s.split(',').map(p => p.trim()).filter(Boolean);
  const nums = parts.map(p => Number(p));
  if (nums.some(n => !Number.isFinite(n))) {
    ctx.addIssue({ code: 'custom', message: 'expected comma-separated numbers' });
    return z.NEVER;
  }
  return nums;
});

const envSchema = z.object({
  TELEGRAM_BOT_TOKEN: z.string().min(1),
  TELEGRAM_WEBHOOK_SECRET: z.string().min(1),
  TELEGRAM_ALLOWED_USERS: csvNumbers,
  ADMIN_TELEGRAM_ID: z.coerce.number().int(),
  LM_STUDIO_URL: z.string().url(),
  LM_STUDIO_MODEL: z.string().min(1),
  EMBEDDING_MODEL: z.string().min(1),
  WHISPER_MODEL: z.string().min(1),
  INTERNAL_NOTIFY_TOKEN: z.string().min(32),
  PORT: z.coerce.number().int().positive(),
  SKILLS_ROOT: z.string().min(1),
  DATA_DIR: z.string().min(1),
});

export type Env = z.infer<typeof envSchema>;

export function loadEnv(source: Record<string, string | undefined> = process.env): Env {
  const parsed = envSchema.safeParse(source);
  if (!parsed.success) {
    const issues = parsed.error.issues.map(i => `  ${i.path.join('.')}: ${i.message}`).join('\n');
    throw new Error(`Invalid environment:\n${issues}`);
  }
  return parsed.data;
}
