# E6 and E7 preparation

Drafted on 2026-10-22 for the held-out check in
[roadmap step 1 after the MVP](../roadmap.md#after-the-mvp-the-demo).
No E6/E7 agent trial was run before the labels were set. Prompts, graders and settings are
unchanged.

Grok Build and Codex checked the labels and agreed with all of them; see
[Review and run](#review-and-run).

## Tasks and evidence

Both properties are residential Berlin addresses. Each task gives only one complete first
message and no commute destinations. Only graders see the labels and fixture names. The live
agent receives no chosen queries, source pages or expected answers.

| Task | Property | Objects, all scored |
|---|---|---|
| [E6](../../evals/tasks/held-out/e6.yaml) | Oberhofer Weg 45, 12209 Berlin | One industry site and five plans |
| [E7](../../evals/tasks/held-out/e7.yaml) | Teltower Straße 31, 14109 Berlin | One industry site, one railway and one plan |

The tasks are in `evals/tasks/held-out/`. Default discovery reads only the top-level YAML
files, so an end-to-end run without explicit paths still selects E1-E5. E6/E7 require
explicit paths. Format checks include the held-out directory.

E7's Nominatim response contains two different places: Steinstücken, postcode 14109, and
Wilhelmstadt, postcode 13597. Production geocoding selects Steinstücken by the postcode
in the task's message; it does not merge the two results.

| Label | Type | Status | Evidence |
|---|---|---|---|
| Heizkraftwerk Lichterfelde | plant | operating | BEW's current generating-site list, naming the site and its gas, heat and electrical output |
| XII-94 | other | null | WFS: housing, streets, private green space |
| XII-181 | other | null | WFS: housing and streets |
| XII-87 | other | null | WFS: school, library, kindergarten, streets and green space |
| XII-159 | other | null | WFS: housing, streets and green space |
| XII-284 | other | null | WFS: kindergarten, gardens, sports ground and traffic areas |
| Katjes Potsdam | production | operating | The operator's factory page: candy production and the exact Wetzlarer Straße address |
| Line 6118 | railway | null | The recorded tracks; the current railway rule leaves their operating status unknown |
| X-129 | other | null | WFS: housing, playground, streets and railway land |

The plan fields establish permitted uses, not whether construction has started. No recorded
evidence establishes construction status. Railway land in a plan does not give it the type
railway under the current plan rules. Plan scan links identify the documents; no label needs
to read a PDF to establish its type. The railway label's URL identifies its OSM element;
it does not claim independent confirmation that trains run now.

BEW's single page supports both the plant type and current use. Katjes' single page supports
both candy manufacturing and current use at the matching address. News about demolition of
old Lichterfelde units does not close the current plant. Katjes' interruption on 8-9 October
2026 is past on the label date. The Katjes site is in Potsdam but within the radius of the
Berlin property; the production query does not stop at the state border.

## Recorded source checks

The Nominatim, Overpass and WFS fixtures were copied unchanged from the address selection and
live preflight. Production code selects all nine labelled objects from them. IDs, coordinates,
categories and distances match the preflight. Map tolerances use `evals.label`'s bounds rule;
plan tolerances are 50 m. The long representative railway way has a 1,600 m tolerance under
that rule. The property is 73 m from its nearest edge, not from the way's centre.

The [Tavily check index](../../evals/fixtures/tavily/README.md) records six searches and
two page reads, made before these tasks. It keeps queries, URL order and selected key facts;
complete original texts remain in ignored local results, as the eval architecture requires.
The selected BEW page ranked fifth in both name-only
queries and third with the map's BEW operator; the selected Katjes page ranked third in both
address queries and first with its name and city. Both extracts succeeded. Identical repeat
queries may be cached; these checks give no long-term success probability.

The chosen industry queries use only map fields and reach the chosen pages within basic
top-five search. Seven other labels are settled by their own recorded map or WFS data. None
is marked `left_out`. No extra search or model call was made to prepare these files.

`evals.label --check` assumes a label without a search has its page URL in its object's
fields. It does not handle the architecture's separate case where those data alone settle
the label, such as this railway. Preparation checks that case locally from the recorded
track instead; a new live reachability call is unnecessary.

Local preparation checks passed on 2026-10-22: both tasks load, production source replay
returns exactly their labelled inventories, and coordinates, categories and tolerances match.
Saved Tavily results contain each industry's chosen page for its written query. The saved
judge calibration checks pass. The existing loader, label, grader, geocoding, map, plan and
investigation tests passed: 243 tests. None of these checks called a model or a network API.

## Review and run

A Grok review confirmed the recorded inventory and its IDs, coordinates, categories and
tolerances. It found two preparation bugs: default task selection included E6/E7, and the
Nominatim README described E7's two places as a duplicate building. Both are fixed, with
regression checks.

Grok Build and Codex checked each label against its evidence and the project definitions:
identity, type, status, search reachability, complete inventory and coordinate tolerances.
Both agreed with all nine labels.

After the fixes, the loader, runner, label and geocoding tests passed: 197 tests. Ruff and
`git diff --check` passed. Default selection gives E1-E5 and explicit selection E6/E7, with
nine held-out labels; the reachability index matches the local responses exactly.

The pair covers plant versus production, housing plans, railway status and a property inside
a plan. The check measures the whole agent; it does not need to exercise the retry for a
rejected finding, which code tests cover. No trial is forced to make a finding fail.

The two tasks ran once at k=3 on 2026-10-22 at c641c71 (six reports, 27 label-trials when
all objects are fetched):

```sh
uv run --env-file .env python -m evals.run --part run_end_to_end --k 3 \
  evals/tasks/held-out/e6.yaml evals/tasks/held-out/e7.yaml
```

Two E7 trials lost the map to an Overpass outage, so E7 ran once more at k=3 at the same
commit, with nothing changed. Both runs cost $0.71 with judges. The results are in the
[MVP eval results](2026-10-21-mvp-eval-results.md#held-out-check), apart from E1-E5. Nothing
is tuned after seeing them.
