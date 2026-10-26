import { useEffect, useRef, useState } from "react";

/** Poll an async data source on an interval; keeps last good data on error. */
export function usePoll<T>(fn: () => Promise<T>, intervalMs: number, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const d = await fnRef.current();
        if (alive) {
          // Keep the previous object when the payload is unchanged so that
          // downstream memos/effects (charts, maps) don't re-render for nothing.
          setData((prev) =>
            prev != null && JSON.stringify(prev) === JSON.stringify(d) ? prev : d,
          );
          setError(null);
        }
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (alive) {
          setLoading(false);
          timer = window.setTimeout(tick, intervalMs);
        }
      }
    };
    setLoading(true);
    tick();
    return () => {
      alive = false;
      if (timer !== undefined) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading };
}
