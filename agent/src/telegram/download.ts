/**
 * Download a file referenced by Telegram file_id.
 *
 * Telegram's file API is a two-step dance:
 *   1) GET /bot<token>/getFile?file_id=… returns { ok, result: { file_path } }
 *   2) GET https://api.telegram.org/file/bot<token>/<file_path> returns bytes
 *
 * Voice messages come back as audio/ogg with the Opus codec.
 */

export interface DownloadOptions {
  botToken: string;
}

export interface DownloadedFile {
  data: Uint8Array;
  /** Filename as reported by Telegram via file_path. Used as filename hint
   *  when forwarding to OpenAI-compatible /audio/transcriptions. */
  filename: string;
  /** Best-effort MIME guess based on file extension. Falls back to ogg/opus
   *  which is Telegram's voice-message default. */
  mimeType: string;
}

const MIME_BY_EXT: Record<string, string> = {
  ogg: 'audio/ogg',
  oga: 'audio/ogg',
  opus: 'audio/ogg',
  mp3: 'audio/mpeg',
  wav: 'audio/wav',
  m4a: 'audio/mp4',
};

function guessMime(filename: string): string {
  const dot = filename.lastIndexOf('.');
  if (dot < 0) return 'audio/ogg';
  const ext = filename.slice(dot + 1).toLowerCase();
  return MIME_BY_EXT[ext] ?? 'application/octet-stream';
}

export async function downloadTelegramFile(opts: DownloadOptions, fileId: string): Promise<DownloadedFile> {
  const metaRes = await fetch(
    `https://api.telegram.org/bot${opts.botToken}/getFile?file_id=${encodeURIComponent(fileId)}`,
  );
  if (!metaRes.ok) {
    throw new Error(`getFile failed: ${metaRes.status} ${await metaRes.text()}`);
  }
  const meta = (await metaRes.json()) as { ok?: boolean; result?: { file_path?: string }; description?: string };
  const filePath = meta.result?.file_path;
  if (!meta.ok || !filePath) {
    throw new Error(`getFile returned no file_path: ${meta.description ?? 'unknown'}`);
  }
  const fileRes = await fetch(`https://api.telegram.org/file/bot${opts.botToken}/${filePath}`);
  if (!fileRes.ok) {
    throw new Error(`file download failed: ${fileRes.status}`);
  }
  const buf = new Uint8Array(await fileRes.arrayBuffer());
  // file_path looks like "voice/file_42.oga" — strip the directory for the
  // filename hint we forward downstream.
  const filename = filePath.split('/').pop() ?? 'voice.oga';
  return { data: buf, filename, mimeType: guessMime(filename) };
}
