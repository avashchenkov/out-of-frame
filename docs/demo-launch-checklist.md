# Demo launch checklist

TODO: complete this checklist before enabling live input. Until then, serve only the reviewed
recorded examples. The [demo architecture](demo-architecture.md) defines behaviour and limits.
This checklist covers the deployed settings and notices; it is not a worldwide legal clearance.

## Operator and visitor information

- [ ] TODO: supply the operator's real name, serviceable postal address and dedicated contact
  email for the Impressum. A forwarding alias keeps the personal inbox private but does not
  replace the name or address. Check the applicable DDG/MStV particulars against the
  [German media regulators' guidance](https://www.die-medienanstalten.de/aufgaben/aufsicht/impressumspflicht/).
  Configure the public email through the page's server environment and keep it working for
  questions, feedback and data requests. A contact form is not needed.
- [ ] TODO: show short service terms before Start: the operator provides a free, limited AI
  report and return access for the configured period. Explain availability, quotas, deletion
  and that the report gives facts, not advice to buy or rent. Make the terms accessible later
  from the footer; they can be a short section, without another dedicated page.
- [ ] TODO: confirm Article 6(1)(b) GDPR for processing objectively necessary under that valid
  service agreement. A Start button requests the service; it is not blanket consent to every
  use of data. Confirm the agreement's validity and the need for the return window using the
  [EDPB guidelines](https://www.edpb.europa.eu/system/files/documents/files/file1/edpb_guidelines-art_6-1-b-adopted_after_public_consultation_en.pdf).
  Assess quota records, region checks and security logs separately under Article 6(1)(f),
  with a brief necessity and balancing record. Visitor content is not reused for examples,
  evals or improvement.
- [ ] TODO: justify the identity cookie's purpose and duration for private access and the
  conversation limit. Strictly necessary storage for an expressly requested service is exempt
  from consent under [section 25(2) TDDDG](https://www.gesetze-im-internet.de/ttdsg/__25.html).
  No separate cookie-acceptance gate is planned. Keep examples and legal pages cookie-free;
  use no analytics, tracking pixels or third-party fonts.
- [ ] TODO: publish an accessible Privacy notice before input and in the footer. Name the
  controller, data types, purposes, legal bases, recipients, transfers and retention periods.
  Include access, correction and deletion rights, contact and the supervisory complaint route.
  Plan for rights requests, normally within one month
  ([EDPB guidance](https://www.edpb.europa.eu/sme/be-compliant/respect-individuals-rights_en)).
  Cookie IDs, IP addresses and free text may be personal data even in a fictional demo.
- [ ] TODO: keep the interface and notices in English for the English-reading adult technical
  audience. Check that the information is understandable to that audience. German hosting or
  nationality alone does not set the notice language; a click does not shift the operator's
  transparency duty to the visitor. If targeting German-speaking people who cannot understand
  English, translate the legal information
  ([WP29 guidance, paragraphs 9 and 13](https://ec.europa.eu/newsroom/article29/redirection/document/51025)).
- [ ] TODO: identify the chat as AI before interaction and keep the report's AI notice,
  credits and source links. Explain that results need checking. Verify the operator's
  applicable [AI Act Article 50](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-50)
  obligations, including output marking where applicable.

## Providers and regions

TODO: name the actual deployed endpoints/providers in the Privacy notice and check this data
flow against outgoing requests:

| Recipient | Request data |
|---|---|
| VPS host | Visitor IP, cookie, HTTP requests and stored conversation |
| Anthropic | Input messages; selected state and source excerpts for research and report generation |
| Nominatim | Property and destination address strings |
| Overpass | Coordinates, search radii and map object IDs |
| Berlin B-Plan WFS | Geographic bounding box and planning-layer names |
| Transitous | Origin/destination coordinates and requested journey dates/times |
| Tavily | Queries about map objects or plans and URLs to extract, not the chat transcript |

- [ ] TODO: verify provider roles, terms and retention for the selected plans and endpoints.
  Put processor agreements in place where needed and verify safeguards for transfers outside
  the EEA. See EDPB guidance on [processors](https://www.edpb.europa.eu/sme/learn-the-basics/data-controller-or-data-processor_en)
  and [international transfers](https://www.edpb.europa.eu/sme/be-compliant/international-data-transfers_en).
- [ ] TODO: describe our server retention separately from provider copies. Anthropic's
  [standard API retention](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data)
  has exceptions; check the actual model and account. Other providers have their own periods.
  Earlier deletion on our server is useful but does not erase their copies.
- [ ] TODO: verify source requests contain only needed data and never forward visitor cookies
  or IP headers. Nominatim's [policy](https://operations.osmfoundation.org/policies/nominatim/)
  prohibits personal/confidential submissions: use public-place queries, without names or
  private notes. Asking for fictional scenarios does not itself filter payloads. Check
  [Tavily's terms](https://www.tavily.com/terms) and the other [source conditions](sources.md#data-rights).
- [ ] TODO: check the provider region/export policies effective at deployment. Anthropic's
  [commercial terms, D.2 and M.8](https://www.anthropic.com/legal/commercial-terms) cover end users;
  check its [API region list](https://platform.claude.com/docs/en/api/supported-regions) and
  regional exceptions. Record the chosen country signal or local database, licence and update
  process; enforce it in Next.js before live requests. Validate the trusted proxy boundary and
  reject browser-supplied country headers. Unknown/unsupported regions get examples.
  Disclose the IP-country check; no passport or nationality collection is planned.
- [ ] TODO: check applicable territorial requirements for live access. The initial scope is
  an adult technical portfolio demo without advertising, data sales or country-specific
  consumer marketing. Provider support alone does not establish legal clearance everywhere.

## Deployment and verification

- [ ] TODO: set HTTPS and runtime secrets; verify only Next.js is publicly reachable. Build
  and inspect the package and image without eval code, judge settings or development tools.
- [ ] TODO: configure deletion and security-log retention from the architecture. Verify Redis
  has no persistence, external tracing is off, private content is not cached or backed up,
  and logs contain no messages or source texts. Measure cleanup timing, including recovery
  after downtime, and make the notice match it.
- [ ] TODO: set separate demo budgets: a monthly cap in a dedicated
  [Anthropic workspace](https://platform.claude.com/docs/en/api/rate-limits#setting-lower-limits-for-workspaces)
  and a credit cap on a dedicated Tavily key, with pay-as-you-go overage disabled.
  Choose amounts with the author and verify them; keep eval usage separate. Tavily's
  [usage API](https://docs.tavily.com/documentation/api-reference/endpoint/usage) exposes the
  key and plan limits. A provider cap may stop an admitted chat before a report.
- [ ] TODO: pass the architecture's [implementation checks](demo-architecture.md#implementation-checks),
  review the static examples and final notices, and complete the approved live trial.

## Before the first message

TODO: place this short notice above `Start private chat`, with the service terms, Privacy
notice, Impressum and author contact accessible. Insert the configured values from
[Demo limits](demo-architecture.md#demo-limits); this text is only the first information layer.
`View examples` stays available without live input.

> English-language AI demo for adults. Use public places and fictional travel plans.
> Start requests a free AI report under the displayed service terms and limits.
> We process your messages, addresses and journey times using Anthropic and the services
> listed in our Privacy notice. Other visitors cannot see your chat or report.
> An essential cookie keeps access and allows up to {chats_per_identity} chats.
> We keep your current chat on our server for up to {identity_lifetime} after your first message.
> Starting another chat does not extend this period.
> New chat or Delete chat removes its content earlier. Clearing cookies loses access;
> it does not delete server data, which is still removed by the original deadline.
> Minimal quota records remain until the cookie expires. Provider retention differs;
> see our Privacy notice. Avoid names and sensitive personal details.
> AI results can be wrong: check the sources.

TODO: when admission is refused, show the specific reason and reset where applicable, followed
by: "Explore the examples, or contact the author with questions or to arrange a demonstration."
