"use client";
import { createContext, useContext } from "react";

// Dialog portals live outside the hidden application surface. Suspend their
// presentation and focus trap without unmounting the owner of the draft state.
export const SessionSuspensionContext = createContext(false);
export function useSessionSuspended() {
  return useContext(SessionSuspensionContext);
}
