/**
 * Quick reachability check for LM Studio.
 *
 * Hits /v1/models with a short timeout. We don't care about the response shape,
 * only that the server is up and answering. Used by the pipeline as a pre-flight
 * check; if this fails we trigger Wake-on-LAN before retrying the actual call.
 */

export interface HealthCheckOptions {
  baseUrl: string;
  timeoutMs?: number;
}

export async function isLmStudioReachable(opts: HealthCheckOptions): Promise<boolean> {
  const timeoutMs = opts.timeoutMs ?? 3000;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${opts.baseUrl}/v1/models`, { signal: ctrl.signal });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}
