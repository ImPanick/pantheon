// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/speechText.js

/**
 * `B1718`. What a reply says out loud, and where to break it so the first
 * words are spoken while the rest is still being written.
 *
 * A reply is Markdown written for the eye: code, tables, links with their
 * addresses, emphasis marks, thinking, emoji. Read as it stands, a voice says
 * "asterisk asterisk", spells out a URL and reads a Python file line by line.
 * `speakableText` keeps the words a person would say and drops the rest.
 *
 * A reply also arrives a few characters at a time, and waiting for all of it
 * before speaking is the pause that makes a voice chat feel like a voicemail.
 * `SpeechChunker` is fed the text so far (the whole of it, every time, as the
 * chat's stream holds it) and answers the sentences that are finished and not
 * yet said. A construct still open at the end — a code fence, a link whose
 * address is still arriving, a `<think>` — is held back until it closes, so a
 * sentence is never spoken and then turned into something else by the next
 * few characters.
 *
 * No DOM: the text is never parsed as HTML (the read-aloud it replaces gave
 * model output to `innerHTML`, where an `<img onerror>` runs), so this module
 * runs under node for its tests (`tests/test_speech_text_*`).
 */

// Words that end in a full stop without ending the sentence. Lower case, the
// dot inside an abbreviation kept (`e.g`), the final one dropped.
const ABBREVIATIONS = new Set([
  'mr', 'mrs', 'ms', 'dr', 'prof', 'sr', 'jr', 'st', 'mt', 'ft', 'vs', 'etc', 'e.g', 'i.e',
  'a.m', 'p.m', 'u.s', 'u.k', 'no', 'nos', 'fig', 'figs', 'approx', 'inc', 'ltd', 'co', 'corp',
  'dept', 'est', 'vol', 'ch', 'sec', 'cf', 'al', 'ca', 'gen', 'gov', 'sen', 'rep', 'ave',
  'blvd', 'rd', 'jan', 'feb', 'mar', 'apr', 'jun', 'jul', 'aug', 'sep', 'sept', 'oct', 'nov',
  'dec', 'mon', 'tue', 'tues', 'wed', 'thu', 'thur', 'thurs', 'fri', 'sat', 'sun', 'min', 'max',
]);

const THINK_OPEN = /<(?:mm:)?(?:think|thinking|thought)(?:\s[^>]*)?>/i;
const THINK_BLOCK = /<(?:mm:)?(?:think|thinking|thought)(?:\s[^>]*)?>[\s\S]*?<\/(?:mm:)?(?:think|thinking|thought)>/gi;
const FENCE_LINE = /^[ \t]{0,3}(```|~~~)/;

/**
 * The text up to the first construct that is still open at its end, so the
 * part handed on can only grow as more arrives. `final` is the whole reply.
 */
export function settledText(text, final = false) {
  let s = String(text || '');
  if (final) return s;
  // Thinking that has not closed is not the reply yet.
  const think = s.replace(THINK_BLOCK, (m) => ' '.repeat(m.length));
  const open = think.search(THINK_OPEN);
  if (open >= 0) s = s.slice(0, open);
  // A code fence that has not closed: everything from it is code.
  const lines = s.split('\n');
  let offset = 0;
  let fenceAt = -1;
  for (const line of lines) {
    if (FENCE_LINE.test(line)) fenceAt = fenceAt < 0 ? offset : -1;
    offset += line.length + 1;
  }
  if (fenceAt >= 0) s = s.slice(0, fenceAt);
  // A table row still being written.
  const lastLine = s.slice(s.lastIndexOf('\n') + 1);
  if (/^\s*\|/.test(lastLine)) s = s.slice(0, s.length - lastLine.length);
  // In the last paragraph: inline code, a link, a tag or a `$$` still open.
  const para = s.lastIndexOf('\n\n') + 1;
  const tail = s.slice(para);
  const ticks = (tail.match(/`/g) || []).length;
  if (ticks % 2 === 1) s = s.slice(0, para + tail.lastIndexOf('`'));
  const bracket = s.lastIndexOf('[');
  if (bracket >= para && !/\]\([^)]*\)|\][^(]/.test(s.slice(bracket)) && s.length - bracket < 400) {
    s = s.slice(0, bracket);
  }
  const lt = s.lastIndexOf('<');
  if (lt >= para && s.indexOf('>', lt) < 0 && s.length - lt < 200) s = s.slice(0, lt);
  const dollars = (s.slice(para).match(/\$\$/g) || []).length;
  if (dollars % 2 === 1) s = s.slice(0, s.lastIndexOf('$$'));
  // An address still arriving: its host is what is said, and it is not known yet.
  const url = s.match(/(?:https?:\/\/|www\.)\S*$/i);
  if (url) s = s.slice(0, url.index);
  return s;
}

function hostOf(address) {
  const m = String(address).match(/^(?:https?:\/\/)?(?:www\.)?([^/\s:?#]+)/i);
  return m ? m[1].replace(/[.,;:!?)\]]+$/, '') : '';
}

/**
 * The words of `markdown` a voice should say. Code blocks, tables, images,
 * thinking and emoji are dropped; links keep their words, bare addresses are
 * said as their host, emphasis and list marks go. Line breaks are kept, as
 * the places a sentence ends without a full stop (a heading, a list item).
 */
export function speakableText(markdown) {
  let s = String(markdown || '');
  if (!s) return '';
  s = s.replace(/\r\n?/g, '\n');
  // Thinking, in the spellings `markdown.js`'s `normalizeThinkingMarkup` reads.
  s = s.replace(THINK_BLOCK, ' ');
  s = s.replace(/<\|channel>thought[\s\S]*?<channel\|>/gi, ' ');
  s = s.replace(/<\|channel>response\s*/gi, '').replace(/<channel\|>/gi, '');
  const think = s.search(THINK_OPEN);
  if (think >= 0) s = s.slice(0, think);
  // Fenced blocks (code, documents, diagrams): none of it is said.
  const out = [];
  let inFence = false;
  for (const line of s.split('\n')) {
    if (FENCE_LINE.test(line)) { inFence = !inFence; out.push(''); continue; }
    if (inFence) continue;
    // Tables, rules and indented code.
    if (/^\s*\|/.test(line)) continue;
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { out.push(''); continue; }
    if (/^(?: {4}|\t)/.test(line) && !/^\s*([-*+]|\d+[.)])\s/.test(line)) continue;
    out.push(line);
  }
  s = out.join('\n');
  // Display maths.
  s = s.replace(/\$\$[\s\S]*?\$\$/g, ' ').replace(/\\\[[\s\S]*?\\\]/g, ' ');
  s = s.replace(/\\\(([\s\S]*?)\\\)/g, ' ');
  // Images, then links (inline, reference, autolink), then bare addresses.
  s = s.replace(/!\[[^\]]*\]\([^)]*\)/g, ' ');
  s = s.replace(/!\[[^\]]*\]\[[^\]]*\]/g, ' ');
  s = s.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1');
  s = s.replace(/\[([^\]]+)\]\[[^\]]*\]/g, '$1');
  s = s.replace(/^\s*\[[^\]]+\]:\s*\S+.*$/gm, '');
  s = s.replace(/\[\^[^\]]*\]/g, '');
  s = s.replace(/<((?:https?:\/\/|www\.)[^>\s]+)>/gi, (_m, a) => hostOf(a));
  s = s.replace(/(?:https?:\/\/|www\.)[^\s<>()]+/gi, (a) => hostOf(a));
  // HTML: a break is a line, other tags go and their words stay.
  s = s.replace(/<br\s*\/?>/gi, '\n');
  s = s.replace(/<\/?[A-Za-z][^>]*>/g, ' ');
  s = s.replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'");
  // Inline code: a short name is said, a long snippet is not.
  s = s.replace(/`([^`\n]*)`/g, (_m, c) => (c.length <= 40 ? c : ' '));
  // Line marks: headings, quotes, list bullets and numbers, task boxes.
  s = s.replace(/^[ \t]*#{1,6}[ \t]+/gm, '');
  s = s.replace(/^[ \t]*>+[ \t]?/gm, '');
  s = s.replace(/^[ \t]*(?:[-*+•]|\d+[.)])[ \t]+(?:\[[ xX]\][ \t]+)?/gm, '');
  // Emphasis and strike marks; an underscore inside a word (`snake_case`) stays.
  s = s.replace(/~~/g, '').replace(/\*+/g, '');
  s = s.replace(/(^|[^\p{L}\p{N}])_+(?=\S)/gu, '$1').replace(/(\S)_+(?=$|[^\p{L}\p{N}])/gu, '$1');
  // Symbols a voice reads badly.
  s = s.replace(/\s*(?:→|->|⟶|=>)\s*/g, ' to ').replace(/\s*(?:←|<-)\s*/g, ' from ');
  s = s.replace(/\s+[—–]\s+|—/g, ', ').replace(/\s&\s/g, ' and ');
  s = s.replace(/[\p{Extended_Pictographic}\u{1F1E6}-\u{1F1FF}\u{FE0F}\u{200D}\u{20E3}]/gu, '');
  // Space: one between words, none before a stop (an emoji taken from
  // between them leaves one), a line where a line was.
  s = s.replace(/[ \t\u00A0]+/g, ' ').replace(/ ([.,;:!?…])/g, '$1');
  // A dash said as a comma after a stop, or at the start of a line, is no
  // pause at all.
  s = s.replace(/([.!?…:;]),+/g, '$1').replace(/(^|\n)[ ,]+/g, '$1');
  s = s.replace(/ *\n */g, '\n').replace(/\n{2,}/g, '\n');
  return s.trim();
}

const SAYABLE = /[\p{L}\p{N}]/u;
const ENDERS = '.!?…';
const CJK_ENDERS = '。！？';

/**
 * Where the sentence starting at `from` ends: the index just past its last
 * character, or -1 when it has not ended yet. A full stop needs a space and
 * then more text after it before it is believed (`Dr.` waits for `Smith`),
 * unless `final` says nothing more is coming.
 */
export function sentenceEnd(s, from = 0, final = false) {
  for (let i = from; i < s.length; i++) {
    const c = s[i];
    if (c === '\n') {
      if (i + 1 < s.length || final) return i + 1;
      return -1;
    }
    if (CJK_ENDERS.includes(c)) return i + 1;
    if (!ENDERS.includes(c)) continue;
    let j = i + 1;
    while (j < s.length && /[.!?…"'”’»)\]]/.test(s[j])) j++;
    if (j >= s.length) return final ? s.length : -1;
    if (!/\s/.test(s[j])) { i = j - 1; continue; }   // 3.14, file.txt, e.g.x
    let k = j;
    while (k < s.length && (s[k] === ' ' || s[k] === '\t')) k++;
    if (k >= s.length) return final ? s.length : -1;
    if (s[k] === '\n') return j;
    if (c === '.' || c === '…') {
      const word = (s.slice(Math.max(0, i - 16), i).match(/([\p{L}][\p{L}.]*)$/u) || [])[1] || '';
      if (ABBREVIATIONS.has(word.toLowerCase())) { i = j - 1; continue; }
      if (/^\p{Lu}$/u.test(word)) { i = j - 1; continue; }        // an initial: J. Smith
      if (/^\p{Ll}/u.test(s[k])) { i = j - 1; continue; }        // goes on in lower case
    }
    return j;
  }
  return final && s.length > from ? s.length : -1;
}

/** The last place before `limit` a long sentence can be broken, at least
 *  `minimum` in: after a clause mark, else (`spaces`) at a space; -1 when
 *  there is neither. */
function breakBefore(s, limit, minimum, spaces = true) {
  const window = s.slice(0, limit);
  let best = -1;
  const clause = /[,;:](?=\s)/g;
  let m;
  while ((m = clause.exec(window))) if (m.index + 1 >= minimum) best = m.index + 1;
  if (best > 0 || !spaces) return best;
  const space = window.lastIndexOf(' ');
  return space >= minimum ? space : -1;
}

/**
 * Sentences for a voice, from a reply that is still being written.
 *
 *   const chunker = new SpeechChunker();
 *   chunker.push(textSoFar)   → [sentences ready to say]
 *   chunker.finish(fullText)  → [whatever was left]
 *
 * The first piece of a reply is let go as early as it can be — at its first
 * sentence end, or at a comma once it is long — because it is what the person
 * waits for. Later ones are whole sentences, short ones joined so a voice is
 * not asked for three words at a time.
 */
export class SpeechChunker {
  constructor({ firstClauseAfter = 80, joinUnder = 60, maxChars = 260 } = {}) {
    this.firstClauseAfter = firstClauseAfter;
    this.joinUnder = joinUnder;
    this.maxChars = maxChars;
    this.reset();
  }

  reset() {
    this._said = 0;          // characters of the speakable text already handed out
    this._pieces = 0;        // pieces handed out since the reset
  }

  push(text) { return this._take(text, false); }

  finish(text) {
    const out = this._take(text, true);
    return out;
  }

  _take(text, final) {
    const speak = speakableText(settledText(text, final));
    if (speak.length <= this._said) return [];
    let rest = speak.slice(this._said);
    let used = 0;
    const sentences = [];
    for (;;) {
      const lead = rest.length - rest.trimStart().length;
      const body = rest.slice(lead);
      if (!body) { used += lead; rest = ''; break; }
      let end = sentenceEnd(body, 0, final);
      if (end < 0 || end > this.maxChars) {
        // The first piece goes at a clause once it is long (a comma, not any
        // space: a voice that stops mid-phrase sounds broken); any piece goes
        // at a clause, or a space, once it is longer than one request holds.
        const first = this._pieces === 0 && sentences.length === 0;
        const limit = Math.min(body.length, this.maxChars);
        let cut = -1;
        if (end < 0 && first && body.length >= this.firstClauseAfter) cut = breakBefore(body, limit, 24, false);
        if (cut < 0 && body.length > this.maxChars) {
          cut = breakBefore(body, limit, 40);
          if (cut < 0) cut = this.maxChars;
        }
        if (cut < 0) break;
        end = cut;
      }
      sentences.push(body.slice(0, end).trim());
      used += lead + end;
      rest = body.slice(end);
    }
    this._said += used;
    const pieces = [];
    for (const sentence of sentences) {
      if (!SAYABLE.test(sentence)) continue;
      const last = pieces.length - 1;
      if (last >= 0 && pieces[last].length < this.joinUnder
          && pieces[last].length + 1 + sentence.length <= this.maxChars) {
        pieces[last] += ' ' + sentence;
      } else {
        pieces.push(sentence);
      }
    }
    this._pieces += pieces.length;
    return pieces;
  }
}

/** A whole text as the pieces a voice says, for a reply already written. */
export function speechPieces(text, options) {
  return new SpeechChunker(options).finish(text);
}

export default { speakableText, settledText, sentenceEnd, SpeechChunker, speechPieces };
