/** Minimal, explicit synthetic PDF used only by the integration test. */
export function syntheticPdf(): Buffer {
  const content =
    "BT /F1 14 Tf 50 740 Td (Synthetic EvidenceDesk QA document) Tj 0 -30 Td /F1 11 Tf (This is test data. It does not describe a real incident.) Tj 0 -24 Td (Compare payment evidence with the order snapshot before concluding.) Tj ET";
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    "<< /Length " +
      Buffer.byteLength(content) +
      " >>\nstream\n" +
      content +
      "\nendstream",
  ];
  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  for (const [index, object] of objects.entries()) {
    offsets.push(Buffer.byteLength(pdf));
    pdf += index + 1 + " 0 obj\n" + object + "\nendobj\n";
  }
  const xref = Buffer.byteLength(pdf);
  pdf +=
    "xref\n0 6\n0000000000 65535 f \n" +
    offsets
      .slice(1)
      .map((offset) => String(offset).padStart(10, "0") + " 00000 n \n")
      .join("");
  pdf += "trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + xref + "\n%%EOF\n";
  return Buffer.from(pdf);
}
