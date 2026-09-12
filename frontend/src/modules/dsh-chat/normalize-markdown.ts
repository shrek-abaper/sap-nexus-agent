// Models sometimes emit slightly malformed markdown over the stream:
// heading/list/rule/quote markers glued to the previous line (e.g.
// "工厂编码### 标题" or "采购组- 需要提供"). GFM then shows the markers
// literally. This inserts the required block boundaries conservatively —
// it only splits on clearly-glued block starts and never touches dates,
// ranges (2026-09-12), or inline hyphenated words.
export function normalizeMarkdown(input: string): string {
  let text = input.replace(/\r\n/g, "\n");

  // "---" rule glued after a CJK character (before bullet splitting so the
  // rule's dashes are not mistaken for list markers).
  text = text.replace(/([一-鿿）)】」』])[ \t]*---[ \t]*(?=\n|$)/g, "$1\n\n---\n\n");

  // Heading glued to preceding text: split only when a non-newline, non-#
  // character directly precedes the hashes ("编码### 标题").
  text = text.replace(/(^|[^\n#\s])([ \t]*)(#{1,6})[ \t]+/g,
    (match, lead: string, _space: string, hashes: string, offset: number) =>
      (offset === 0 ? match : `${lead}\n\n${hashes} `));

  // Glued bullet. Two safe cases:
  //  (a) after sentence punctuation: "：-需要", "码 - 需要";
  //  (b) a CJK word directly followed by "-<CJK>" mid-line, but never on a
  //      heading line (those start with #, where "诊断-查询" is a title, not
  //      a list). "--"/"---" rules are excluded by the lookahead.
  text = text
    .replace(/([：；。！？）)】」』])[ \t]*[-*](?![-*])[ \t]*/g, "$1\n- ")
    .split("\n")
    .map((line) => {
      if (/^\s{0,3}#{1,6}\s/.test(line)) return line; // leave heading lines intact
      // CJK word glued to a mid-line marker: "编码-需要" -> split.
      const split = line.replace(/([一-鿿）)】」』])[ \t]*[-*](?![-*])(?=[一-鿿])[ \t]*/g, "$1\n- ");
      // Line-start marker with no following space: "-需要" -> "- 需要".
      return split.replace(/^(\s{0,3})[-*](?![-*\s])(?=[一-鿿])/, "$1- ");
    })
    .join("\n");

  // Blockquote glued after text.
  text = text.replace(/([^\n>])[ \t]*>[ \t]+/g, "$1\n\n> ");

  text = text.replace(/\n{3,}/g, "\n\n");
  return text.trim();
}
