// @ts-check
/**
 * Text helpers for the llms.txt plugin. They work on markdown as text, with no Docusaurus in them,
 * so they can be run and checked on their own.
 */

// A link's description is one sentence. A longer opening is cut at a word, with an ellipsis.
const DESCRIPTION_LIMIT = 220;
const FENCE = /^\s*(`{3,}|~{3,})/;
const MDX_IMPORT = /^import\s.+\sfrom\s+['"][^'"]+['"];?\s*$/;
// The first line of a block that is not prose: a heading, an image, JSX, a table, a rule, a quote or a list.
const NOT_PROSE = /^(#|!\[|<|\||---|>|[-*+]\s|\d+\.\s)/;

/** One line of plain text: no line breaks, no emphasis marks, at most one sentence. */
function oneSentence(text) {
  const flat = String(text ?? '')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1') // a link keeps its words
    .replace(/[*`]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  if (!flat) return '';
  // The first full stop that ends a sentence: followed by a space or the end, and not an abbreviation.
  const end = flat.search(/(?<!\b(?:e\.g|i\.e|etc|vs))[.!?](?=\s|$)/);
  let sentence = end > 0 ? flat.slice(0, end + 1) : flat;
  // An opening that leads into a list ("there are two kinds:") reads as a sentence with a full stop.
  sentence = sentence.replace(/:$/, '.');
  // An opening that breaks off, because a code block or a diagram interrupts it, keeps the clause
  // before its last colon: that part is complete.
  if (!/[.!?]$/.test(sentence)) {
    const colon = sentence.lastIndexOf(': ');
    if (colon > 20) sentence = `${sentence.slice(0, colon)}.`;
  }
  if (sentence.length <= DESCRIPTION_LIMIT) return sentence;
  return `${sentence.slice(0, DESCRIPTION_LIMIT).replace(/\s+\S*$/, '')}...`;
}

/**
 * Applies `change` to every line that is not inside a fenced code block, and drops a line when
 * `change` returns null. Code is left exactly as written.
 */
function outsideCode(markdown, change) {
  let fence = '';
  const lines = [];
  for (const line of markdown.split('\n')) {
    const mark = line.match(FENCE);
    if (mark) {
      if (!fence) fence = mark[1][0];
      else if (mark[1][0] === fence) fence = '';
      lines.push(line);
    } else if (fence) {
      lines.push(line);
    } else {
      const changed = change(line);
      if (changed !== null) lines.push(changed);
    }
  }
  return lines.join('\n');
}

/**
 * A page's markdown as an assistant should read it: no front matter and no MDX import lines.
 * An `import` inside a code sample is part of the sample and stays.
 */
function bodyOf(source) {
  const withoutFrontMatter = source.replace(/^---\n[\s\S]*?\n---\n/, '');
  return outsideCode(withoutFrontMatter, (line) => (MDX_IMPORT.test(line) ? null : line)).trim();
}

/**
 * The opening paragraph of a page: the first block of prose after the title. Headings, images,
 * tables, lists, quotes, JSX, code and admonitions are passed over. The lines of the paragraph
 * are joined, so a sentence that is hard-wrapped in the source comes back whole.
 */
function openingOf(body) {
  const blocks = [];
  let block = [];
  let fence = '';
  let inAdmonition = false;
  const close = () => {
    if (block.length > 0) blocks.push(block);
    block = [];
  };
  for (const raw of body.split('\n')) {
    const line = raw.trim();
    const mark = raw.match(FENCE);
    if (mark) {
      if (!fence) fence = mark[1][0];
      else if (mark[1][0] === fence) fence = '';
      close();
    } else if (fence) {
      // inside code
    } else if (line.startsWith(':::')) {
      inAdmonition = line !== ':::';
      close();
    } else if (!line) {
      close();
    } else if (!inAdmonition) {
      block.push(line);
    }
  }
  close();
  const prose = blocks.find((lines) => !NOT_PROSE.test(lines[0]));
  return prose ? prose.join(' ') : '';
}

/**
 * Rewrites the targets of markdown links and images outside code, through `resolve`.
 * Absolute links, mail links and in-page anchors are left alone.
 */
function rewriteLinks(markdown, resolve) {
  return outsideCode(markdown, (line) =>
    line.replace(/\]\(([^)\s]+)(\s+"[^"]*")?\)/g, (whole, target, title = '') => {
      if (/^(?:[a-z][a-z0-9+.-]*:|#|<)/i.test(target)) return whole;
      return `](${resolve(target)}${title})`;
    }),
  );
}

module.exports = { oneSentence, outsideCode, bodyOf, openingOf, rewriteLinks };
