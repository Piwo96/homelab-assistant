import { describe, it, expect } from 'bun:test';
import { markdownToTelegramHtml } from '../src/telegram/format';

describe('markdownToTelegramHtml', () => {
  it('converts **bold** to <b>', () => {
    expect(markdownToTelegramHtml('Hallo **Welt**')).toBe('Hallo <b>Welt</b>');
  });

  it('converts inline `code` to <code>', () => {
    expect(markdownToTelegramHtml('Wert `light.kitchen` an'))
      .toBe('Wert <code>light.kitchen</code> an');
  });

  it('converts leading bullet (* or -) to Unicode •', () => {
    const input = '* Erstes\n- Zweites\n  * Eingerückt';
    expect(markdownToTelegramHtml(input)).toBe('• Erstes\n• Zweites\n• Eingerückt');
  });

  it('handles the real-world Rolly reply', () => {
    const input = 'Die folgenden Lampen sind eingeschaltet:\n*   **OG Flur Beleuchtung 2** (`light.og_flur_beleuchtung_2`)\n*   **Wandleuchten Schlafzimmer** (`light.wandleuchten_schlafzimmer`)';
    const expected = 'Die folgenden Lampen sind eingeschaltet:\n• <b>OG Flur Beleuchtung 2</b> (<code>light.og_flur_beleuchtung_2</code>)\n• <b>Wandleuchten Schlafzimmer</b> (<code>light.wandleuchten_schlafzimmer</code>)';
    expect(markdownToTelegramHtml(input)).toBe(expected);
  });

  it('html-escapes raw < > & so tags cannot be injected', () => {
    expect(markdownToTelegramHtml('1 < 2 & 3 > 0'))
      .toBe('1 &lt; 2 &amp; 3 &gt; 0');
    expect(markdownToTelegramHtml('<script>alert(1)</script>'))
      .toBe('&lt;script&gt;alert(1)&lt;/script&gt;');
  });

  it('converts ``` fenced code blocks to <pre>', () => {
    const input = '```\nfoo bar\n```';
    expect(markdownToTelegramHtml(input)).toBe('<pre>foo bar</pre>');
  });

  it('does not turn underscores inside entity_ids into italics', () => {
    expect(markdownToTelegramHtml('Geräte: light.og_flur_beleuchtung_2 und sensor.temp_wohnzimmer'))
      .toBe('Geräte: light.og_flur_beleuchtung_2 und sensor.temp_wohnzimmer');
  });

  it('converts standalone _italic_ when surrounded by whitespace/punctuation', () => {
    expect(markdownToTelegramHtml('Das ist _wichtig_ hier'))
      .toBe('Das ist <i>wichtig</i> hier');
  });
});
