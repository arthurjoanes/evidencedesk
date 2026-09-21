import { Suspense } from "react";
import { IncidentQueue } from "@/features/incidents/incident-queue";
import { Loading } from "@/components/feedback";
export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <IncidentQueue />
    </Suspense>
  );
}
