import { createHmac, timingSafeEqual } from "node:crypto";

export const COOKIE_NAME = "oof_identity";
export const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function readIdentity(cookieHeader: string | null, secret: string) {
  const cookies = (cookieHeader ?? "").split(";").map((part) => part.trim());
  const matches = cookies.filter((part) => part.startsWith(`${COOKIE_NAME}=`));
  if (matches.length !== 1) return null;

  const token = matches[0].slice(COOKIE_NAME.length + 1);
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const [identity, expiry, signature] = parts;
  if (!UUID.test(identity) || !/^[1-9][0-9]{0,10}$/.test(expiry)) return null;
  if (!/^[0-9a-f]{64}$/.test(signature)) return null;
  if (Number(expiry) * 1000 <= Date.now()) return null;

  const expected = createHmac("sha256", secret)
    .update(`${identity}.${expiry}`)
    .digest();
  if (!timingSafeEqual(expected, Buffer.from(signature, "hex"))) return null;
  return { identity, expires: Number(expiry) };
}
