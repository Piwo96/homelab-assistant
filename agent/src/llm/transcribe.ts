/**
 * Transcribe audio via LM Studio's OpenAI-compatible /v1/audio/transcriptions
 * endpoint. LM Studio exposes Whisper models (e.g. whisper-large-v3-turbo)
 * through the same API shape as OpenAI's transcription endpoint.
 *
 * The endpoint expects multipart/form-data with at least `file` and `model`.
 */

export interface TranscribeConfig {
  baseUrl: string;
  model: string;
}

export interface AudioInput {
  data: Uint8Array;
  filename: string;
  mimeType: string;
}

export async function transcribeAudio(cfg: TranscribeConfig, input: AudioInput): Promise<string> {
  const form = new FormData();
  // Bun's Blob accepts Uint8Array directly; type is supplied so the OpenAI-
  // compatible server picks the right decoder (ogg/opus vs wav vs mp4).
  form.append('file', new Blob([input.data], { type: input.mimeType }), input.filename);
  form.append('model', cfg.model);
  // Force German — Whisper's auto-detect is good but Rolly is German-only,
  // and a confident "de" hint cuts false-positives on short clips.
  form.append('language', 'de');
  form.append('response_format', 'json');

  const res = await fetch(`${cfg.baseUrl}/v1/audio/transcriptions`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) {
    throw new Error(`transcribe failed: ${res.status} ${await res.text()}`);
  }
  const body = (await res.json()) as { text?: string };
  return (body.text ?? '').trim();
}
