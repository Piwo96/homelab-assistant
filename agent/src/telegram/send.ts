import { markdownToTelegramHtml } from './format';

export interface SendOptions {
  botToken: string;
}

export async function sendText(opts: SendOptions, chatId: number, text: string): Promise<number> {
  const html = markdownToTelegramHtml(text);
  const res = await fetch(`https://api.telegram.org/bot${opts.botToken}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_id: chatId, text: html, parse_mode: 'HTML' }),
  });
  if (!res.ok) {
    throw new Error(`sendMessage failed: ${res.status} ${await res.text()}`);
  }
  const body = (await res.json()) as { result?: { message_id?: number } };
  return body.result?.message_id ?? 0;
}

/**
 * Edit an existing bot message in-place. Used to swap the "⌛ working on it…"
 * placeholder with the real reply once the pipeline completes.
 */
export async function editText(
  opts: SendOptions,
  chatId: number,
  messageId: number,
  text: string,
): Promise<void> {
  const html = markdownToTelegramHtml(text);
  const res = await fetch(`https://api.telegram.org/bot${opts.botToken}/editMessageText`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_id: chatId, message_id: messageId, text: html, parse_mode: 'HTML' }),
  });
  if (!res.ok) {
    throw new Error(`editMessageText failed: ${res.status} ${await res.text()}`);
  }
}

/**
 * Best-effort: delete a previously-sent bot message. Used to clean up the
 * "⌛ Ich kümmere mich darum..." placeholder when the pipeline decides to
 * suppress its reply (e.g. a debounced duplicate /start). Errors are
 * swallowed — failing to delete a stale placeholder is annoying but not
 * worth aborting the request flow.
 */
export async function deleteMessage(
  opts: SendOptions,
  chatId: number,
  messageId: number,
): Promise<void> {
  try {
    await fetch(`https://api.telegram.org/bot${opts.botToken}/deleteMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: chatId, message_id: messageId }),
    });
  } catch {
    // best-effort cleanup; ignore failures
  }
}

export interface BotCommand {
  command: string;
  description: string;
}

/**
 * Register a list of /commands so Telegram shows them in the slash-menu and
 * autocomplete. Idempotent — Telegram replaces the existing list on every
 * call, so it's safe to run on every bot startup.
 */
export async function setMyCommands(opts: SendOptions, commands: BotCommand[]): Promise<void> {
  const res = await fetch(`https://api.telegram.org/bot${opts.botToken}/setMyCommands`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ commands }),
  });
  if (!res.ok) {
    throw new Error(`setMyCommands failed: ${res.status} ${await res.text()}`);
  }
}

/**
 * Show "...is typing" in Telegram for ~5s. Best-effort: errors are swallowed
 * so a flaky network never aborts the surrounding pipeline.
 */
export async function sendChatAction(
  opts: SendOptions,
  chatId: number,
  action: 'typing' | 'upload_photo' | 'record_voice' | 'upload_voice' = 'typing',
): Promise<void> {
  try {
    await fetch(`https://api.telegram.org/bot${opts.botToken}/sendChatAction`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: chatId, action }),
    });
  } catch {
    // best-effort indicator; ignore failures
  }
}
