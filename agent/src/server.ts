import type { Database } from 'bun:sqlite';
import { verifySecret, isDuplicate, markProcessed, parseUpdate } from './telegram/webhook';
import { sendText, editText, sendChatAction, deleteMessage } from './telegram/send';
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

  setTimeout(async () => {
    const sendOpts = { botToken: deps.env.TELEGRAM_BOT_TOKEN };

    // Two parallel feedback channels while the pipeline runs:
    //  1. "Rolly tippt..." chat action (refreshed every 4s; expires at 5s)
    //  2. A real placeholder message "⌛ Ich kümmere mich darum..." that
    //     gets edited in place with the real reply once ready.
    void sendChatAction(sendOpts, parsed.chatId, 'typing');
    const typingInterval = setInterval(() => {
      void sendChatAction(sendOpts, parsed.chatId, 'typing');
    }, 4000);

    let placeholderId = 0;
    try {
      placeholderId = await sendText(sendOpts, parsed.chatId, '⌛ Ich kümmere mich darum...');
    } catch (err) {
      log.warn('placeholder_send_failed', { err: String(err), updateId: parsed.updateId });
    }

    handleMessage(deps.handleDeps, parsed)
      .then(async reply => {
        clearInterval(typingInterval);
        if (!reply) {
          // Pipeline suppressed the response (e.g. debounced duplicate
          // /start). Clean up the placeholder so the chat doesn't show
          // a stale "⌛" bubble.
          if (placeholderId) {
            await deleteMessage(sendOpts, parsed.chatId, placeholderId);
          }
          return;
        }
        if (placeholderId) {
          await editText(sendOpts, parsed.chatId, placeholderId, reply);
        } else {
          // Placeholder couldn't be sent; fall back to a fresh message.
          await sendText(sendOpts, parsed.chatId, reply);
        }
      })
      .catch(async err => {
        clearInterval(typingInterval);
        log.error('handle_failed', { err: String(err), updateId: parsed.updateId });
        const errMsg = '⚠️ Da ist etwas schiefgegangen. Versuch es nochmal oder check `journalctl -u rolly`.';
        try {
          if (placeholderId) await editText(sendOpts, parsed.chatId, placeholderId, errMsg);
          else await sendText(sendOpts, parsed.chatId, errMsg);
        } catch (e) {
          log.error('error_reply_failed', { err: String(e) });
        }
      });
  }, 0);

  return new Response('ok', { status: 200 });
}
