"use client";

import { useEffect, useRef, useState } from "react";
import { useInView } from "@/hooks/use-in-view";

export function StatCounter({ value, label }: { value: string; label: string }) {
  const { ref, inView } = useInView();
  const [display, setDisplay] = useState("0");
  const started = useRef(false);

  useEffect(() => {
    if (!inView || started.current) return;
    started.current = true;

    // If value isn't purely numeric, just snap to it after a short delay
    const num = parseFloat(value.replace(/[^0-9.]/g, ""));
    if (isNaN(num)) {
      const t = setTimeout(() => setDisplay(value), 300);
      return () => clearTimeout(t);
    }

    const prefix = value.match(/^[^0-9]*/)?.[0] ?? "";
    const suffix = value.match(/[^0-9.]*$/)?.[0] ?? "";
    const duration = 1200;
    const steps = 40;
    let step = 0;

    const interval = setInterval(() => {
      step++;
      const progress = step / steps;
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = Math.round(eased * num * 10) / 10;
      setDisplay(`${prefix}${current % 1 === 0 ? current : current.toFixed(1)}${suffix}`);
      if (step >= steps) {
        setDisplay(value);
        clearInterval(interval);
      }
    }, duration / steps);

    return () => clearInterval(interval);
  }, [inView, value]);

  return (
    <div ref={ref} className="text-center">
      <div className="text-4xl font-bold tracking-tight text-foreground md:text-5xl">
        {display}
      </div>
      <div className="mt-2 text-sm text-muted-foreground">{label}</div>
    </div>
  );
}
