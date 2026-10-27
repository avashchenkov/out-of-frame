import { mutationProxy } from "./mutation-proxy.ts";
import { busyResponse, readProxy } from "./read-proxy.ts";
import type { ProxyConfig } from "./read-proxy.ts";
import { demoTraffic } from "./traffic-limits.ts";

export async function proxyRequest(
  request: Request,
  path: string[],
  config: ProxyConfig,
  fetchBackend: typeof fetch = fetch,
  traffic = demoTraffic(),
) {
  // Count anonymous requests and reconnects too. Refuse before reading a body,
  // reserving admission quota or contacting the private backend.
  if (!traffic.allowRequest()) return busyResponse();
  return request.method === "GET"
    ? readProxy(request, path, config, fetchBackend, traffic)
    : mutationProxy(request, path, config, fetchBackend);
}
