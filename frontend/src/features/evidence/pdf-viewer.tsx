"use client";
import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { PDFDocumentProxy } from "pdfjs-dist";
import { apiUrl } from "@/lib/http";
import { Button } from "@/components/ui/button";
import { ErrorNotice, Loading } from "@/components/feedback";

export function PdfViewer({
  url,
  initialPage,
}: {
  url: string;
  initialPage: number;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(initialPage);
  const [error, setError] = useState<unknown>();
  useEffect(() => {
    let cancelled = false;
    let loadingTask:
      ReturnType<typeof import("pdfjs-dist").getDocument> | undefined;
    void import("pdfjs-dist")
      .then((pdfjs) => {
        if (cancelled) return;
        pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";
        loadingTask = pdfjs.getDocument({
          url: apiUrl(url),
          withCredentials: true,
          standardFontDataUrl: "/pdf/standard_fonts/",
          cMapUrl: "/pdf/cmaps/",
          cMapPacked: true,
          wasmUrl: "/pdf/wasm/",
        });
        return loadingTask.promise.then((pdf) => {
          if (!cancelled) setDocument(pdf);
        });
      })
      .catch((failure: unknown) => {
        if (!cancelled) setError(failure);
      });
    return () => {
      cancelled = true;
      void loadingTask?.destroy();
    };
  }, [url]);
  useEffect(() => {
    if (!document || !canvas.current) return;
    let cancelled = false;
    let renderTask:
      | ReturnType<Awaited<ReturnType<PDFDocumentProxy["getPage"]>>["render"]>
      | undefined;
    const element = canvas.current;
    void document
      .getPage(Math.min(page, document.numPages))
      .then((pdfPage) => {
        if (cancelled) return;
        const viewport = pdfPage.getViewport({ scale: 1.4 });
        const context = element.getContext("2d");
        if (!context) throw new Error("Canvas indisponível.");
        element.width = viewport.width;
        element.height = viewport.height;
        renderTask = pdfPage.render({
          canvas: element,
          canvasContext: context,
          viewport,
        });
        return renderTask.promise;
      })
      .catch((failure: unknown) => {
        if (!cancelled) setError(failure);
      });
    return () => {
      cancelled = true;
      renderTask?.cancel();
    };
  }, [document, page]);
  if (error !== undefined)
    return (
      <>
        <ErrorNotice error={error} />
        <p className="evidence-role">
          O PDF não pôde ser renderizado. Use “Texto canônico” para continuar
          conferindo a evidência.
        </p>
      </>
    );
  return (
    <div>
      {!document && <Loading>Carregando documento…</Loading>}
      {document && (
        <div className="pdf-tools">
          <Button
            size="small"
            disabled={page <= 1}
            onClick={() => setPage((current) => current - 1)}
            aria-label="Página anterior do PDF"
          >
            <ChevronLeft size={14} />
          </Button>
          <span>
            Página {Math.min(page, document.numPages)} de {document.numPages}
          </span>
          <Button
            size="small"
            disabled={page >= document.numPages}
            onClick={() => setPage((current) => current + 1)}
            aria-label="Próxima página do PDF"
          >
            <ChevronRight size={14} />
          </Button>
        </div>
      )}
      <div className="pdf-canvas">
        <canvas
          ref={canvas}
          role="img"
          aria-label={
            "Página " +
            page +
            " do documento. Texto acessível na opção Texto canônico."
          }
        />
      </div>
    </div>
  );
}
