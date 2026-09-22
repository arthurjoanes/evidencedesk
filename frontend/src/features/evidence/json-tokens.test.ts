import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { CanonicalContent } from "./canonical-content";
import { tokenizeJson } from "./json-tokens";
import { formatJsonForReading } from "./reconciliation-content";

describe("JSON syntax presentation", () => {
  it("preserves original bytes represented by the string, including duplicate keys and precise numbers", () => {
    const original =
      ' \r\n{"n":9007199254740993,"n":1.00e+02,"escaped":"\\u0041, { \\\" ok","unicode":"ação 東京","values":[true,false,null,-0]}\t';
    for (const text of [original, formatJsonForReading(original)!]) {
      const tokens = tokenizeJson(text);
      expect(tokens.map((token) => token.text).join("")).toBe(text);
      expect(
        tokens
          .filter((token) => token.kind === "number")
          .map((token) => token.text),
      ).toEqual(["9007199254740993", "1.00e+02", "-0"]);
      expect(
        tokens
          .filter((token) => token.kind === "literal")
          .map((token) => token.text),
      ).toEqual(["true", "false", "null"]);
      expect(
        tokens.filter((token) => token.kind === "key" && token.text === '"n"'),
      ).toHaveLength(2);
    }
  });

  it("distinguishes a key from identical string content and leaves keyword-like strings intact", () => {
    const tokens = tokenizeJson(
      '{"same" \n : "same", "text": "true null -12 { }"}',
    );
    expect(
      tokens
        .filter((token) => token.text === '"same"')
        .map((token) => token.kind),
    ).toEqual(["key", "string"]);
    expect(
      tokens.filter(
        (token) => token.kind === "literal" || token.kind === "number",
      ),
    ).toEqual([]);
  });

  it("escapes source HTML through React instead of inserting markup", () => {
    const text =
      '{"payload":"<img src=x onerror=alert(1)><script>alert(1)</script>"}';
    const html = renderToStaticMarkup(
      createElement(CanonicalContent, { text }),
    );
    expect(html).toContain('class="language-json"');
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;");
    expect(html).not.toContain("<img");
    expect(html).not.toContain("<script");
  });

  it.each([
    "Uma fonte textual, sem linguagem de programação.",
    '{"incomplete":',
  ])("keeps non-JSON and invalid JSON as ordinary text: %s", (text) => {
    const html = renderToStaticMarkup(
      createElement(CanonicalContent, { text }),
    );
    expect(html).not.toContain("language-json");
    expect(html).not.toContain("<span");
  });
});
