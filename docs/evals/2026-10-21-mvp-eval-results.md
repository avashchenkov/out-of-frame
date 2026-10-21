# MVP eval results

The MVP's eval results on 2026-10-21, before and after the fixes of roadmap steps 8 to 10:
one page per finding and the plan rules (8), the agent's effort (9), and the classification
funnel, railways in code and one more try for a rejected finding (10). How each suite is built
and graded is in the [eval architecture](../eval-architecture.md).

| | Before | After |
|---|---|---|
| Code | 58fa3fa, 2026-10-18 | 30b09d7, 2026-10-21 |
| Agent | Claude Haiku 5.5, default effort (medium) | Claude Haiku 5.5, high effort |
| Judges | Claude Haiku 5.5, extra-high effort, calibrated | the same |

The fixes were made on these same tasks, so the "after" column shows that they work here, not
how the agent does at addresses it was not tuned on.

## End-to-end

Five Berlin addresses, E1–E5, three trials each, live: map, plans, transit and web search as
they were that day. Both runs are graded against the labels of 2026-10-21: 32 scored labels,
so 96 label-trials. A label left out is scored on neither side (see
[Labels left out](#labels-left-out)).

| | Before | After |
|---|---|---|
| Labels passed: correct in two trials of three at least | 27 of 32 | 32 of 32 |
| Of them unstable: correct in two trials of three | 2 | 2 |
| Labels failed | 5 | 0 |
| Label-trials correct | 80 of 96 | 94 of 96 |
| Wrong claims: a wrong type or status | 9 | 1 |
| Abstentions: unidentified or an unknown status where the label has one | 7 | 1 |
| False alarms | 0 | 0 |
| Support judge: statements unsupported or contradicted | 13 of 185 | 11 of 199 |
| Interpretation judge: reports passed | 13 of 15 | 15 of 15 |
| No-verdict judge: reports passed | 15 of 15 | 15 of 15 |
| Tool calls | 320 | 355 |
| Cost: agent, judges | $2.71, $0.29 | $3.51, $0.31 |
| Trials with a failed source | 2, an address query each | none |

The after run is the full run of 2026-10-21 at 30b09d7. Three of its trials, E2 2, E3 3 and
E4 2, lost the map or the address query to the public Overpass server (502), and were run again
the same day until every source answered: E3 and E4 once, E2 twice. The before run is the full
run of step 7, graded again against the same labels.

What turned, in two trials of three at least:

- **Railways, 6 wrong claims before.** The agent took lines 6179 (E1) and 6045 (E2) for in
  use from their map tags; code now gives every railway an unknown status, as their labels.
- **Plans, 10 errors before.** V-13, XV-18, XV-19, XV-23 and XV-25: a housing or a mixed area
  is other, and a core area commercial. All right in every trial now.

The two unstable labels, each wrong in one trial of three:

- **plan-2-56e (E3), a wrong claim.** The page says workshops and offices stand on the plots
  now; the agent took them for what the plan allows, production in use. The plan names only
  business areas, so it has no type. Plans come from another source than the map, so the
  trial of E3 that lost the map graded this label too: it failed the same way, as did the
  trial run in its place.
- **jenoptik-diode-lab (E5), an unknown status.** The search found the firm's ISO certificate,
  not its directory entry, and a certificate does not show the site in use today.

One more try for a rejected finding ran 5 times in the 15 trials and saved 3 findings.

**Conclusion.** Every scored label passes, and wrong claims fell from 9 to 1. Two labels are
unstable: a search that found another page, and a plan rule that the model applied wrongly
once. Live search and the model vary from trial to trial, so one miss in three on a label is
expected spread, not a failure of the agent; a person reviews the results either way. Within
the limits below, the agent does what the MVP set out to do.

## Component suites

Each suite runs each task three times; a task passes in a trial on its own criterion. Tasks
were added with the fixes, so a suite can have more tasks after than before. The before runs
are of 2026-10-18 at the code before step 8, except Enough, which was built in step 9 and first
ran on 2026-10-20 at the default effort.

| Suite | Before: trials passed | After: trials passed |
|---|---|---|
| Triage | T1, T2: 6 of 6 | T1, T2, T4: 6 of 9 |
| Finding | F1, F2, F4–F8: 21 of 21 | F1, F2, F4–F20: 56 of 57 |
| Enough | N1–N6: 17 of 18 | N1–N6: 14 of 18 |
| Live investigation | L1: 3 of 3 | L1: 3 of 3 |
| Input loop | I1–I3: 9 of 9 | I1–I3: 9 of 9 |
| Injection check | P1–P4: 12 of 12, no false alarms or misses | the same |
| Report | R2–R4: 9 of 9 | R2–R4: 9 of 9 |

The failures after:

- **T4, in every trial.** A stormwater filter that the map tags as a wastewater plant: the
  model takes it for a sewage works by what it knows. Its end-to-end label is left out; T4
  stays as a task that fails, until triage tells the filter apart.
- **F10, once.** The model answered without the Finding tool. The finding suite grades the
  model's call alone; in the agent, such an answer gets one more try.
- **N3, in every trial, and N5 once.** At high effort the agent searches once more where a
  newer register already settles the object, a search more within the cap, not a wrong
  finding; and once it did not read a page whose snippet lacked the facts. Step 9 chose high
  effort for the findings and the reports, which did better at it, against this cost.

## Labels left out

68 labels in E1–E5: 32 scored, 36 left out, each with its reason in its task file.

- **No page within the agent's reach, 14.** No page about the object, none that a search of
  5 results at Tavily's basic depth finds by what the agent sees, or only a plan's PDF:
  Klärwerkstraße 1 (E1), AMR Dachbaustoffe (E4), line 6107 (E1) and plan 8-81B (E2) among
  them. The [search-depth spike](../../spikes/search-depth/findings-2026-10-16.md) found that
  some of these pages are within Tavily's reach at a higher cost, and some need other words.
- **Left out of the MVP, 22.** Listed with their reasons in
  [Labels left out of the MVP](../eval-architecture.md#labels-left-out-of-the-mvp): 8 whose page
  the search does not reliably reach, 6 railways whose page shows trains running, 5 that the
  rules do not settle, and 3 left out earlier.

## Known limitations

- Whether trains run on a line: code gives every railway an unknown status.
- A map tag that misleads the model's own knowledge, such as a rainwater filter tagged as a
  wastewater plant: triage takes it for a sewage works (T4, which still fails).
- A site that several businesses share: the search by address finds some of them, not always
  the one that affects people nearby the most.
- An unnamed site whose page the search misses, and a page out of date or one that gives a
  site's planned uses as current.
- A use that only a plan's documents name, such as a PDF of its reasons: the agent reads no
  plan PDFs.
- A plan replaced in part by another, and a plan whose state shows only on a page about one of
  its plots.
- A plan's type from the uses on its land today rather than from what it allows (plan-2-56e).

## The one-page rule

A finding rests on one page, so that the facts of one business are not mixed with another's.
Its cost in the end-to-end scores is not seen directly: each label records the one page that
shows why it is true. The one label that no single page settles, nlnd-campus (E2), is left out.

## Cost and time

One report costs about $0.23 for the agent at high effort, and its three judges about $0.02.
A trial takes about six minutes.
