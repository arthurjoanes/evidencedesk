import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/classes";

const variants = cva("button", {
  variants: {
    variant: {
      primary: "button-primary",
      secondary: "button-secondary",
      ghost: "button-ghost",
      danger: "button-danger",
    },
    size: { normal: "", small: "button-small", icon: "button-icon" },
  },
  defaultVariants: { variant: "secondary", size: "normal" },
});
type Props = ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof variants> & { asChild?: boolean };
export function Button({
  className,
  variant,
  size,
  asChild,
  type = "button",
  ...props
}: Props) {
  const Component = asChild ? Slot : "button";
  return (
    <Component
      type={asChild ? undefined : type}
      className={cn(variants({ variant, size }), className)}
      {...props}
    />
  );
}
