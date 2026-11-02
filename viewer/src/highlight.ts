import type { HighlighterCore } from "shiki/core";

const MAX_HIGHLIGHT_LINES = 6000;
let highlighter: Promise<HighlighterCore> | null = null;

function load(): Promise<HighlighterCore> {
  highlighter ??= (async () => {
    const [{ createHighlighterCore }, { createJavaScriptRegexEngine }] = await Promise.all([
      import("shiki/core"),
      import("shiki/engine/javascript"),
    ]);
    return createHighlighterCore({
      themes: [import("shiki/themes/github-dark-default.mjs")],
      langs: [import("shiki/langs/python.mjs")],
      engine: createJavaScriptRegexEngine(),
    });
  })();
  return highlighter;
}

const escape = (text: string) =>
  text.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]!);

/** Python source as HTML, one `.line` span per line, lines in `range` marked `.hl`. */
export async function highlightPython(code: string, range?: [number, number] | null): Promise<string> {
  const marked = (line: number) => Boolean(range && line >= range[0] && line <= range[1]);
  if (code.split("\n").length > MAX_HIGHLIGHT_LINES) {
    const lines = code
      .split("\n")
      .map((text, i) => `<span class="line${marked(i + 1) ? " hl" : ""}">${escape(text)}</span>`);
    return `<pre class="shiki"><code>${lines.join("\n")}</code></pre>`;
  }
  return (await load()).codeToHtml(code, {
    lang: "python",
    theme: "github-dark-default",
    transformers: [
      {
        line(node, line) {
          if (marked(line)) this.addClassToHast(node, "hl");
        },
      },
    ],
  });
}
