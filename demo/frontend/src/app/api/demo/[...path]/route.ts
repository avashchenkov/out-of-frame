import {
  disabledRoute,
  proxyConfig,
  unavailable,
} from "../../../../server/read-proxy.ts";
import { proxyRequest } from "../../../../server/proxy.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function handle(
  request: Request,
  { params }: { params: Promise<{ path: string[] }> },
) {
  try {
    return await proxyRequest(
      request,
      (await params).path,
      proxyConfig(process.env),
    );
  } catch {
    return unavailable();
  }
}

export {
  handle as GET,
  handle as POST,
  disabledRoute as PUT,
  disabledRoute as PATCH,
  handle as DELETE,
  disabledRoute as HEAD,
  disabledRoute as OPTIONS,
};
