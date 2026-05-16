/**
 * Convert generic markdown (as produced by the LLM) into the subset of HTML
 * that Telegram accepts with parse_mode: "HTML".
 *
 * Telegram HTML supports: <b>, <strong>, <i>, <em>, <u>, <s>, <code>, <pre>,
 * <a href>, <span class="tg-spoiler">. NO <ul>/<li> — bullets must be literal
 * Unicode dots.
 *
 * Order matters: we escape HTML first so user content can't smuggle tags,
 * then apply markdown patterns (which still match because escaping doesn't
 * touch * _ ` characters).
 */
export function markdownToTelegramHtml(input: string): string {
  let s = input.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  // Fenced code blocks ```...```  → <pre>...</pre>
  s = s.replace(/```([\s\S]*?)```/g, (_, body: string) => `<pre>${body.trim()}</pre>`);

  // Inline code `...` → <code>...</code>
  s = s.replace(/`([^`\n]+)`/g, '<code>$1</code>');

  // Bold **text** → <b>text</b>  (handle before single-asterisk italic)
  s = s.replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>');

  // Underscore-italic _text_  (avoid matching inside identifiers like light.og_flur_2)
  s = s.replace(/(^|[\s(])_([^_\n]+)_(?=$|[\s.,;:!?)])/g, '$1<i>$2</i>');

  // Bullet lines:  "* item"  or  "- item"  at line start → "• item"
  s = s.replace(/^[ \t]*[\*\-][ \t]+/gm, '• ');

  return s;
}
