# Demo: legitimate interest record

A short record for the two kinds of processing that the
[Privacy notice](../demo/frontend/src/app/privacy/page.tsx) bases on Article 6(1)(f) GDPR.
The private chat itself is based on Article 6(1)(b). Recorded on 2026-10-25 for the
[launch checklist](demo-launch-checklist.md).

## Usage limit records

**Data.** Per browser cookie: a random ID, its expiry, the number of chats and submissions,
a reference to the current chat and pending-deletion bookkeeping. Across all visitors: the
number of new chats per day. No messages, addresses or IP addresses.

**Interest.** Keep a free demo available to many visitors and keep its provider costs
limited. Without limits, one visitor could use up the daily capacity or the provider budget.

**Necessity.** The limits need a count per browser and per day; the cookie ID is the
smallest identifier that allows this. There is no account, fingerprinting or IP-based limit.

**Balancing.** The visitor expects a free service to have limits; the start notice shows
them before the first message. The records hold no content, are not shared and end with
the cookie, at most the configured lifetime after the first message. The impact on the
visitor is low.

**Result.** The interest prevails. Visitors can object by writing to the contact address.

## Security logs

**Data.** For each request: client IP address, time, method, path and response status,
in Caddy's access log on our server. No headers, cookies or request bodies.

**Interest.** Detect misuse, attacks and errors, and keep the service secure.

**Necessity.** The IP address and time are needed to recognise repeated or abusive
requests. Paths and status show errors and scans. Nothing else is logged.

**Balancing.** Visitors expect a public website to keep short security logs. The log stays
on our server, is not shared or analysed for other purposes and is deleted after
24 hours. The impact on the visitor is low.

**Result.** The interest prevails. Visitors can object by writing to the contact address.
