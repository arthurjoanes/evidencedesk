"use client";
import * as Primitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { useSessionSuspended } from "@/lib/session-suspension";
import { Button } from "./button";

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  wide = false,
  onCloseAutoFocus,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  children: ReactNode;
  wide?: boolean;
  onCloseAutoFocus?: (event: Event) => void;
}) {
  const suspended = useSessionSuspended();
  return (
    <Primitive.Root open={open && !suspended} onOpenChange={onOpenChange}>
      <Primitive.Portal>
        <Primitive.Overlay className="dialog-overlay" />
        <Primitive.Content
          className={"dialog-content" + (wide ? " dialog-wide" : "")}
          onCloseAutoFocus={onCloseAutoFocus}
        >
          <div className="dialog-heading">
            <div>
              <Primitive.Title>{title}</Primitive.Title>
              <Primitive.Description>{description}</Primitive.Description>
            </div>
            <Primitive.Close asChild>
              <Button size="icon" variant="ghost" aria-label="Fechar">
                <X size={18} />
              </Button>
            </Primitive.Close>
          </div>
          {children}
        </Primitive.Content>
      </Primitive.Portal>
    </Primitive.Root>
  );
}
