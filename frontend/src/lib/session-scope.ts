import type { Session } from "./contracts";

export function scopeKey(session: Session) {
  // The CSRF token is session-specific. Keep it internal to the query key:
  // a replacement session must never inherit another session's cached resources.
  return [
    session.tenant.id,
    session.user.id,
    session.expires_at,
    session.csrf_token,
  ];
}
