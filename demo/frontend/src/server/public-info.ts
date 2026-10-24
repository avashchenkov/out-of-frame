import { proxyConfig } from "./read-proxy.ts";

export type Operator = {
  name?: string;
  address: string[];
  email?: string;
  hostingProvider?: string;
};

export type PublicLimits = {
  identity_chats: number;
  lifetime_days: number;
  submissions: number;
  message_chars: number;
};

const EMAIL = /^[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+$/;

function text(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed && trimmed.length <= 200 && !/[<>]/.test(trimmed)
    ? trimmed
    : undefined;
}

export function contactEmail(env: NodeJS.ProcessEnv): string | undefined {
  const email = env.OUT_OF_FRAME_DEMO_CONTACT_EMAIL?.trim() ?? "";
  return EMAIL.test(email) ? email : undefined;
}

export function operatorDetails(env: NodeJS.ProcessEnv): Operator {
  const address = text(env.OUT_OF_FRAME_DEMO_OPERATOR_ADDRESS);
  return {
    name: text(env.OUT_OF_FRAME_DEMO_OPERATOR_NAME),
    // Address lines are separated by semicolons in the environment.
    address: address
      ? address
          .split(";")
          .map((line) => line.trim())
          .filter(Boolean)
      : [],
    email: contactEmail(env),
    hostingProvider: text(env.OUT_OF_FRAME_DEMO_HOSTING_PROVIDER),
  };
}

// Server-side read for notice pages: no visitor cookie or IP is forwarded.
export async function publicLimits(
  env: NodeJS.ProcessEnv,
  fetchBackend: typeof fetch = fetch,
): Promise<PublicLimits | null> {
  try {
    const config = proxyConfig(env);
    const response = await fetchBackend(
      new URL("/demo/limits", config.backend),
      {
        headers: { "x-demo-key": config.secret },
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.timeout(5_000),
      },
    );
    if (!response.ok) return null;
    const data = await response.json();
    const limits = {
      identity_chats: data?.identity_chats,
      lifetime_days: data?.lifetime_days,
      submissions: data?.submissions,
      message_chars: data?.message_chars,
    };
    return Object.values(limits).every(
      (value) => Number.isSafeInteger(value) && value > 0,
    )
      ? limits
      : null;
  } catch {
    return null;
  }
}
