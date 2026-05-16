import type { Database } from 'bun:sqlite';
import { verifySecret, isDuplicate, markProcessed, parseUpdate } from './telegram/webhook';
import { sendText } from './telegram/send';
import type { HandleDeps } from './pipeline/handle-message';
import { handleMessage } from './pipeline/handle-message';
import { log } from './utils/logger';
import type { Env } from './config/env';

export interface ServerDeps {
  env: Env;
  db: Database;
  handleDeps: HandleDeps;
}

const TELEGRAM_SECRET_HEADER = 'X-Telegram-Bot-Api-Secret-Token';

export function startServer(deps: ServerDeps): { stop: () => void } {
  const allowed = new Set(deps.env.TELEGRAM_ALLOWED_USERS);
  const server = Bun.serve({
    port: deps.env.PORT,
    async fetch(req) {
      const url = new URL(req.url);
      if (req.method === 'GET' && url.pathname === '/health') {
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }
      if (req.method === 'POST' && url.pathname === '/webhook') {
        return handleWebhook(req, deps, allowed);
      }
      return new Response('not found', { status: 404 });
    },
  });
  log.info('server_started', { port: deps.env.PORT });
  return { stop: () => server.stop() };
}

async function handleWebhook(req: Request, deps: ServerDeps, allowed: Set<number>): Promise<Response> {
  const secret = req.headers.get(TELEGRAM_SECRET_HEADER);
  if (!verifySecret(deps.env.TELEGRAM_WEBHOOK_SECRET, secret)) {
    log.warn('webhook_bad_secret');
    return new Response('forbidden', { status: 403 });
  }
  let body: unknown;
  try { body = await req.json(); } catch { return new Response('bad json', { status: 400 }); }
  const update = body as { update_id: number };
  if (typeof update.update_id !== 'number') return new Response('bad update', { status: 400 });
  if (isDuplicate(deps.db, update.update_id)) {
    log.info('webhook_duplicate', { updateId: update.update_id });
    return new Response('ok', { status: 200 });
  }
  markProcessed(deps.db, update.update_id);
  const parsed = parseUpdate(update as never);
  if (!parsed) return new Response('ok', { status: 200 });

  if (!allowed.has(parsed.userId)) {
    log.warn('webhook_unauthorized_user', { userId: parsed.userId });
    return new Response('ok', { status: 200 });
  }

  setTimeout(() => {
    handleMessage(deps.handleDeps, parsed)
      .then(reply => sendText({ botToken: deps.env.TELEGRAM_BOT_TOKEN }, parsed.chatId, reply))
      .catch(err => log.error('handle_failed', { err: String(err), updateId: parsed.updateId }));
  }, 0);

  return new Response('ok', { status: 200 });
}
