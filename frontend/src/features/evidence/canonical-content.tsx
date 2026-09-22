"use client";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { formatJsonForReading } from "./reconciliation-content";
import { tokenizeJson } from "./json-tokens";
import styles from "./canonical-content.module.css";

export function CanonicalContent({ text }: { text: string }) {
  const [formatted, setFormatted] = useState(false);
  const readable = useMemo(() => formatJsonForReading(text), [text]);
  const displayed = formatted && readable !== null ? readable : text;
  const tokens = useMemo(
    () => (readable !== null ? tokenizeJson(displayed) : null),
    [displayed, readable],
  );
  return (
    <>
      {readable !== null && (
        <div className="canonical-format">
          <Button
            size="small"
            variant="secondary"
            aria-pressed={formatted}
            onClick={() => setFormatted(!formatted)}
          >
            {formatted ? "Mostrar JSON original" : "Formatar JSON para leitura"}
          </Button>
          <p>
            {formatted
              ? "JSON com espaços e quebras visuais; valores e escapes preservados. O hash se refere ao original."
              : "JSON original da evidência, sem reformatação."}
          </p>
        </div>
      )}
      <pre
        className={
          "evidence-text" +
          (readable !== null ? " evidence-json " + styles.json : "")
        }
        tabIndex={0}
        role="region"
        aria-label="Texto canônico da fonte"
      >
        {tokens ? (
          <code className="language-json">
            {tokens.map((token) =>
              token.kind === "plain" ? (
                token.text
              ) : (
                <span key={token.offset} className={styles[token.kind]}>
                  {token.text}
                </span>
              ),
            )}
          </code>
        ) : (
          displayed || "Esta fonte não possui texto extraído disponível."
        )}
      </pre>
    </>
  );
}
