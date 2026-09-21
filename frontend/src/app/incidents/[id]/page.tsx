import { Suspense } from "react";
import { IncidentWorkspace } from "@/features/incidents/incident-workspace";
import { Loading } from "@/components/feedback";
export default async function IncidentPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <Suspense fallback={<Loading>Abrindo incidente…</Loading>}>
      <IncidentWorkspace id={id} />
    </Suspense>
  );
}
