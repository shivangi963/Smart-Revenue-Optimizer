import { useCallback, useEffect, useRef, useState } from 'react';

// Load data on mount (and whenever `deps` change); optionally poll.
export function useAsync(fn, deps = [], pollMs = 0) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const counter = useRef(0);

  const run = useCallback(async (silent = false) => {
    const id = ++counter.current;
    if (!silent) setState((s) => ({ ...s, loading: true }));
    try {
      const data = await fnRef.current();
      if (id === counter.current) setState({ data, error: null, loading: false });
    } catch (error) {
      if (id === counter.current) setState((s) => ({ data: silent ? s.data : null, error, loading: false }));
    }
  }, []);

  useEffect(() => {
    run(false);
    if (!pollMs) return undefined;
    const t = setInterval(() => run(true), pollMs);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const reload = useCallback(() => run(false), [run]);
  return { ...state, reload };
}

export function useDebounced(value, ms = 400) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}
