import { queryString } from "@/lib/http";
export function queueDestination(params: Pick<URLSearchParams, "get">) {
  const status = params.get("return_status");
  return (
    "/" +
    queryString({
      q: params.get("return_q"),
      status:
        status && ["open", "in_review", "resolved"].includes(status)
          ? status
          : null,
    })
  );
}
export function incidentDestination(
  id: string,
  params: Pick<URLSearchParams, "get">,
) {
  return (
    "/incidents/" +
    encodeURIComponent(id) +
    queryString({
      return_q: params.get("q"),
      return_status: params.get("status"),
    })
  );
}
export function workspaceDestination(
  pathname: string,
  current: string,
  snapshot: string,
  changes: Record<string, string | null>,
) {
  const next = new URLSearchParams(current);
  if (!next.has("snapshot")) next.set("snapshot", snapshot);
  for (const [key, value] of Object.entries(changes)) {
    if (value) next.set(key, value);
    else next.delete(key);
  }
  return pathname + "?" + next;
}
