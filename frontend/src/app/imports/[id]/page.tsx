import { ImportDetail } from "@/features/imports/import-detail";
export default async function ImportPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <ImportDetail id={id} />;
}
