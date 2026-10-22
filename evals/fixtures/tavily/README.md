# Held-out source checks

`held-out-reachability.json` summarises production `TavilyWebSearch` checks made on
2026-10-22 before any E6/E7 agent run. It preserves the six queries, settings, response
metadata, URL order, two page lengths and selected key facts. It contains no complete page
or snippet text and no API keys. It is preparation evidence, not a task input.

Original responses remain in the ignored local directory
`evals/results/residential-tavily-preflight-2026-10-22/`, under the file names in the index.
This follows the eval architecture's rule that complete web pages stay in local results.

Searches used basic depth, five results and one attempt. Page reads used the production
40,000-character cap. No model, injection checker or judge ran. Repeated queries may have
been cached; these are reachability checks, not independent statistical trials.

Six searches and two page reads cost an estimated $0.0512 at the project price table.
Preparing this index made no further paid calls. Key facts retain their original URLs.
See the
[preparation note](../../../docs/evals/2026-10-22-held-out-tasks.md).
