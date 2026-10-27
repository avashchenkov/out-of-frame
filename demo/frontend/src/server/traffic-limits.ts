type TrafficConfig = {
  streams: number;
  streamsPerIdentity: number;
  requestsPerSecond: number;
  requestBurst: number;
};

export function trafficConfig(env: NodeJS.ProcessEnv): TrafficConfig {
  function positive(name: string, fallback: number) {
    const value = env[`OUT_OF_FRAME_DEMO_${name}`];
    if (value === undefined) return fallback;
    if (!/^[1-9][0-9]*$/.test(value) || !Number.isSafeInteger(Number(value)))
      throw new Error(`Invalid demo traffic setting: ${name}`);
    return Number(value);
  }
  return {
    streams: positive("STREAMS", 10),
    streamsPerIdentity: positive("STREAMS_PER_IDENTITY", 2),
    requestsPerSecond: positive("REQUESTS_PER_SECOND", 20),
    requestBurst: positive("REQUEST_BURST", 40),
  };
}

// The deployment runs one Next.js process. Reservations are synchronous, before
// any upstream await; only identities with open streams occupy the map.
export class TrafficLimits {
  private readonly config: TrafficConfig;
  private readonly now: () => number;
  private tokens: number;
  private updated: number;
  private streams = 0;
  private readonly owners = new Map<string, number>();

  constructor(
    config: TrafficConfig,
    now: () => number = () => performance.now(),
  ) {
    this.config = config;
    this.now = now;
    this.tokens = config.requestBurst;
    this.updated = now();
  }

  allowRequest(): boolean {
    const now = this.now();
    this.tokens = Math.min(
      this.config.requestBurst,
      this.tokens +
        (Math.max(0, now - this.updated) * this.config.requestsPerSecond) /
          1000,
    );
    this.updated = now;
    if (this.tokens < 1) return false;
    this.tokens--;
    return true;
  }

  openStream(identity: string): (() => void) | null {
    const count = this.owners.get(identity) ?? 0;
    if (
      this.streams >= this.config.streams ||
      count >= this.config.streamsPerIdentity
    )
      return null;
    this.streams++;
    this.owners.set(identity, count + 1);
    let released = false;
    return () => {
      if (released) return;
      released = true;
      this.streams--;
      const remaining = this.owners.get(identity)! - 1;
      if (remaining) this.owners.set(identity, remaining);
      else this.owners.delete(identity);
    };
  }
}

// Keep one budget across route module reloads as well as GET/POST/DELETE.
const shared = globalThis as typeof globalThis & {
  outOfFrameTraffic?: TrafficLimits;
};

export function demoTraffic() {
  return (shared.outOfFrameTraffic ??= new TrafficLimits(
    trafficConfig(process.env),
  ));
}
