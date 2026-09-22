export type JsonTokenKind =
  "key" | "string" | "number" | "literal" | "punctuation" | "plain";

export type JsonToken = { kind: JsonTokenKind; text: string; offset: number };

// Tokenize validated JSON without parsing/re-serializing its values. Keep every
// original character, including duplicate keys, numeric precision and escapes.
const syntax =
  /(?<key>"(?:\\.|[^"\\])*")(?=\s*:)|(?<string>"(?:\\.|[^"\\])*")|(?<number>-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)|(?<literal>true|false|null)|(?<punctuation>[{}\[\],:])/g;

export function tokenizeJson(text: string): JsonToken[] {
  const tokens: JsonToken[] = [];
  let cursor = 0;
  for (const match of text.matchAll(syntax)) {
    if (match.index > cursor) {
      tokens.push({
        kind: "plain",
        text: text.slice(cursor, match.index),
        offset: cursor,
      });
    }
    const kind = Object.keys(match.groups!).find(
      (group) => match.groups![group] !== undefined,
    ) as JsonTokenKind;
    tokens.push({ kind, text: match[0], offset: match.index });
    cursor = match.index + match[0].length;
  }
  if (cursor < text.length)
    tokens.push({ kind: "plain", text: text.slice(cursor), offset: cursor });
  return tokens;
}
