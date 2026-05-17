import { markdownToTelegramHtml } from './format';

export interface SendOptions {
  botToken: string;
}

export async function sendText(opts: SendOptions, chatId: number, text: string): Promise<void> {
  const html = markdownToTelegramHtml(text);
  const res = await fetch(`https://api.telegram.org/bot${opts.botToken}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_id: chatId, text: html, parse_mode: 'HTML' }),
  });
  if (!res.ok) {
    throw new Error(`sendMessage failed: ${res.status} ${await res.text()}`);
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
