import type { ComponentProps } from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

const variants = cva(
  "inline-flex items-center justify-center gap-2 disabled:pointer-events-none",
  {
    variants: { variant: { primary: "primary", outline: "button" } },
    defaultVariants: { variant: "primary" },
  },
);
export function Button({
  asChild = false,
  variant,
  className,
  ...props
}: ComponentProps<"button"> &
  VariantProps<typeof variants> & { asChild?: boolean }) {
  const Component = asChild ? Slot : "button";
  return (
    <Component
      data-slot="button"
      className={twMerge(clsx(variants({ variant }), className))}
      {...props}
    />
  );
}
