import {
  disabledRoute,
  proxyConfig,
  readProxy,
  unavailable,
} from "../../../../server/read-proxy.ts";
import { mutationProxy } from "../../../../server/mutation-proxy.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ path: string[] }> },
) {
  try {
    return await readProxy(
      request,
      (await params).path,
      proxyConfig(process.env),
    );
  } catch {
    return unavailable();
  }
}

async function mutate(
  request: Request,
  { params }: { params: Promise<{ path: string[] }> },
) {
  try {
    return await mutationProxy(
      request,
      (await params).path,
      proxyConfig(process.env),
    );
  } catch {
    return unavailable();
  }
}

export {
  mutate as POST,
  disabledRoute as PUT,
  disabledRoute as PATCH,
  mutate as DELETE,
  disabledRoute as HEAD,
  disabledRoute as OPTIONS,
};
