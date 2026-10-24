import {
  disabledRoute,
  proxyConfig,
  readProxy,
  unavailable,
} from "../../../../server/read-proxy.ts";

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

export {
  disabledRoute as POST,
  disabledRoute as PUT,
  disabledRoute as PATCH,
  disabledRoute as DELETE,
  disabledRoute as HEAD,
  disabledRoute as OPTIONS,
};
