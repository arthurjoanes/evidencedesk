import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
const hopHeaders = [
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
];

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  const base = new URL(process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8106");
  const target = new URL(
    "/api/v1/" + path.map(encodeURIComponent).join("/"),
    base,
  );
  target.search = request.nextUrl.search;
  const headers = new Headers(request.headers);
  for (const name of hopHeaders) headers.delete(name);
  const init: RequestInit & { duplex?: "half" } = {
    method: request.method,
    headers,
    redirect: "manual",
    cache: "no-store",
    signal:
      path.at(-1) === "events"
        ? request.signal
        : AbortSignal.any([request.signal, AbortSignal.timeout(30_000)]),
  };
  if (!["GET", "HEAD"].includes(request.method)) {
    init.body = request.body;
    init.duplex = "half";
  }
  try {
    const upstream = await fetch(target, init);
    const responseHeaders = new Headers(upstream.headers);
    for (const name of hopHeaders) responseHeaders.delete(name);
    responseHeaders.delete("content-encoding");
    responseHeaders.set("Cache-Control", "no-store");
    return new Response(upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch {
    return Response.json(
      {
        error: {
          code: "api_unavailable",
          message: "A API está indisponível. Tente novamente em instantes.",
          request_id: crypto.randomUUID(),
          retryable: true,
        },
      },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}
export {
  proxy as GET,
  proxy as POST,
  proxy as PUT,
  proxy as DELETE,
  proxy as PATCH,
  proxy as HEAD,
};
