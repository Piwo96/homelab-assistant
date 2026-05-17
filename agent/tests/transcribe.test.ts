import { describe, it, expect, afterEach } from 'bun:test';
import { transcribeAudio } from '../src/llm/transcribe';

const origFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = origFetch; });

describe('transcribeAudio', () => {
  it('POSTs multipart form to /v1/audio/transcriptions with model + language', async () => {
    let calledUrl = '';
    let calledForm: FormData | null = null;
    globalThis.fetch = (async (input: Parameters<typeof fetch>[0], init?: Parameters<typeof fetch>[1]) => {
      calledUrl = String(input);
      calledForm = init?.body as FormData;
      return new Response(JSON.stringify({ text: '  Hallo Rolly  ' }), { status: 200 });
    }) as unknown as typeof fetch;

    const result = await transcribeAudio(
      { baseUrl: 'http://lm:1234', model: 'whisper-large-v3-turbo' },
      { data: new Uint8Array([1, 2, 3, 4]), filename: 'voice.oga', mimeType: 'audio/ogg' },
    );

    expect(result).toBe('Hallo Rolly');
    expect(calledUrl).toBe('http://lm:1234/v1/audio/transcriptions');
    expect(calledForm).not.toBeNull();
    expect(calledForm!.get('model')).toBe('whisper-large-v3-turbo');
    expect(calledForm!.get('language')).toBe('de');
    const file = calledForm!.get('file') as Blob | null;
    expect(file).not.toBeNull();
    expect(file!.size).toBe(4);
  });

  it('surfaces server errors with status + body', async () => {
    globalThis.fetch = (async () =>
      new Response('model not loaded', { status: 503 })
    ) as unknown as typeof fetch;

    await expect(
      transcribeAudio(
        { baseUrl: 'http://lm:1234', model: 'whisper' },
        { data: new Uint8Array(), filename: 'a.oga', mimeType: 'audio/ogg' },
      ),
    ).rejects.toThrow(/503.*model not loaded/);
  });
});
