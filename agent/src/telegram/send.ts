export interface SendOptions {
  botToken: string;
}

export async function sendText(opts: SendOptions, chatId: number, text: string): Promise<void> {
  const res = await fetch(`https://api.telegram.org/bot${opts.botToken}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_id: chatId, text, parse_mode: 'HTML' }),
  });
  if (!res.ok) {
    throw new Error(`sendMessage failed: ${res.status} ${await res.text()}`);
  }
}
