"use client";

import { type ReactNode } from "react";

import { cn } from "@/lib/utils";
import { useInView } from "@/hooks/use-in-view";

interface Props {
  children: ReactNode;
  delay?: number;
  className?: string;
  from?: "bottom" | "left" | "right";
}

export function AnimatedEntry({ children, delay = 0, className, from = "bottom" }: Props) {
  const { ref, inView } = useInView();

  const hidden =
    from === "left"
      ? "-translate-x-8 opacity-0"
      : from === "right"
        ? "translate-x-8 opacity-0"
        : "translate-y-8 opacity-0";

  return (
    <div
      ref={ref}
      style={{ transitionDelay: `${delay}ms` }}
      className={cn(
        "transition-all duration-700 ease-out",
        inView ? "opacity-100 translate-x-0 translate-y-0" : hidden,
        className,
      )}
    >
      {children}
    </div>
  );
}
