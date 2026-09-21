import { expect, it } from "vitest";
import type { Session } from "./contracts";
import { scopeKey } from "./session-scope";
const session: Session = {
  user: { id: "one", name: "Name", role: "analyst" },
  tenant: { id: "t1", name: "Tenant" },
  csrf_token: "session-a",
  expires_at: "later",
  permissions: [],
  runtime: {
    generation_enabled: false,
    provider: "disabled",
    model_display_name: "Disabled",
    disabled_reason: null,
  },
};
it("keeps the same session boundary through a harmless refresh", () => {
  expect(
    scopeKey({ ...session, user: { ...session.user, name: "Updated name" } }),
  ).toEqual(scopeKey(session));
});
it("separates replacement sessions even with identical user, tenant and expiration", () => {
  expect(scopeKey({ ...session, csrf_token: "session-b" })).not.toEqual(
    scopeKey(session),
  );
});
it("separates different users and tenants", () => {
  expect(
    scopeKey({ ...session, user: { ...session.user, id: "two" } }),
  ).not.toEqual(scopeKey(session));
  expect(
    scopeKey({ ...session, tenant: { ...session.tenant, id: "t2" } }),
  ).not.toEqual(scopeKey(session));
});
