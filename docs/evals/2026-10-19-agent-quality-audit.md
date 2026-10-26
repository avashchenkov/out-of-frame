# Agent quality audit, 2026-10-19

An evidence review to guide eval-driven optimization: improving the agent's decisions,
evidence use and reports. This records causes and possible interventions before choosing
changes. It does not change the architecture or the roadmap.

Reviewed: saved E1–E5 runs from 18 October, component runs from 19 October, baseline prompts
at `a7cea3b`, the search-depth experiment from 16 October, and current code at `7005abe`.
No new paid calls were made. PDF failures are excluded from the search diagnosis here;
Overpass failures are not attributed to Tavily.

An **instruction violation** means that a rule already existed and the available input
allowed the model to follow it. It is not evidence from a model comparison: a stronger model
has not yet been tested. **Not established** does not mean that improvement is impossible.

## Four axes of improvement

These are four groups of interventions, with evaluation quality checked separately.
They are not independent error counts, and one failure can involve several of them.

| Axis | What can change | What it can address | Evidence in this project |
|---|---|---|---|
| 1. Task rules and prompts | Type definitions, status criteria, source eligibility, scope of claims, search and stopping instructions | A wrong decision made while following an incomplete or ambiguous rule | Default operating status in triage; type boundaries; the state of a whole plan inferred from one plot |
| 2. The model's execution of rules | Model and effort, with the same rules and inputs | Missing or misapplying an instruction that was already sufficient | Violations in classification, evidence_id/key_facts and reports; improvement from another model or effort is not measured |
| 3. Retrieval of needed evidence | Search coverage and returned text, HTML extraction, and, if needed, another source or search provider | Missing facts without which an answer cannot be supported | Wider or deeper search returned additional HTML pages in the control experiment; an E2E gain is not measured |
| 4. Architecture and execution limits | Action budget, evidence passed between steps, correction after validation, structured state and deterministic rendering | A needed step being unavailable, lost context, or errors when restating known data | The constraints are confirmed in code; most proposed changes have not been compared experimentally |

The investigation's system prompt belongs to axis 1. Its choice of query or page under a
sufficient instruction belongs to axis 2. The search response belongs to axis 3. A hard
tool-call cap belongs to axis 4. `max_results` and `search_depth` are configuration settings
whose main effect is on axis 3. Do not count an error twice because the interventions overlap.

If the input lacks a necessary fact, a better prompt or model cannot replace that fact.
They may help obtain it through an available next action, or correctly leave the answer
unknown. If no permitted source provides the fact, an honest unknown is a limit of the
evidence, not necessarily an agent error.

An instruction violation does not prove that model size was the cause. It justifies a
comparison of models or effort on the same inputs. Longer prompts, more results and more
tool calls do not guarantee better answers either.

### Are any axes missing?

**For the failures reviewed here, no further independent major axis of agent improvement
has been established.** The four groups cover the observed mechanisms. This is a useful
map for this audit, not a claim that every possible agent failure has been ruled out.

Context selection, tool design, retries, verification and deterministic output are covered
by axis 4, rather than omitted alternatives. Missing or stale evidence belongs to axis 3;
misreading available evidence belongs to axis 2, provided the rules were sufficient.

**Labels and graders are a separate evaluation concern.** They can make a correct answer
look wrong, or miss a real fault. Fixing them improves the measurement, not the agent's
answer directly. Software and infrastructure failures are outside this audit's scope;
missing addresses after an Overpass failure are not a Tavily or model failure.

## Baseline and current applicability

- After label corrections and the exclusion of two plans, the saved E1–E5 baseline has
  **113 correct out of 159 scored object-trial comparisons, with 46 errors**: 26 wrong claims
  and 20 abstentions, comprising 16 unidentified objects and 4 unknown statuses. These are
  rescored saved outputs, not a new agent run.
- Field errors overlap: 34 type mismatches and 25 status mismatches, with both fields wrong
  in 13 comparisons. Report-text findings are graded separately; they are not additional
  independent failures to add to the 46.
- The full run predates step 10.8. That step clarified several classification rules and
  stopped reading PDFs linked from plan data. Component runs on 19 October still show
  errors, but there is no full E1–E5 rerun after 10.8. Historical failures must not all be
  described as unresolved failures of the current version.
- Five addresses demonstrate mechanisms; they do not estimate accuracy across Berlin or
  support claims about small percentage differences between prompts.

## What the search evidence shows

1. **Wiesendamm, E1.** In trial 1, `Wiesendamm 15 13597 Berlin` did not return the
   Das Örtliche page for the vehicle-recycling business. The agent chose a directory of
   other businesses and returned commercial / operating. In trials 2–3,
   `Wiesendamm 15, 13597 Berlin` returned the relevant HTML page with its address,
   Autoverwertung and opening hours, but the finding remained unidentified. One response
   lacked the needed result; receiving it in the other trials was still insufficient for
   success. The punctuation differs, so this is not a controlled identical-query comparison.
2. **Sprenger, Klärwerkstraße 1A.** In the controlled search experiment, basic/5 missed the
   needed site twice for the same query. Advanced/20 found it in both repetitions, at
   positions 2 and 3/5. This was an HTML metalworking site, not a PDF.
3. **AMR, Besenbinderstraße 23.** Basic/5 missed amr-shop.de twice in the same experiment.
   Basic/20 found it once out of two repetitions, advanced/20 twice. In full E4 trials 1–2,
   the findings were commercial and other. In trial 3, the model added AMR to its query,
   obtained the HTML page with `Herstellung von Profilen`, and still returned unidentified.
   This demonstrates a retrieval limitation for the original query, not that Tavily cannot
   find the site or that a provider change is necessary.
4. **Leisten-Beyer.** The control query for Neuköllnische Allee 52 returned the firm's own
   HTML site with 20 results but not with 5. In failing E2 trials 2–3, however, the model
   did not query that address: it searched Grenzallee 11 and, in trial 2, Neuköllnische
   Allee 54. These E2 failures cannot be attributed to Tavily alone.
5. **CURVE.** Tavily returned the correct BEOS URL in all three E4 trials. Its 578-character
   snippet lacked manufacturing and current manufacturer-tenant information. The model
   never called extract on that page and chose a rental offer instead. The received text
   lacked the facts, and an available next step was unused. A Tavily failure to extract that
   HTML page was not tested.
6. **MOLL / former DS Smith.** The relevant North Data page was already among the results
   in E2 trials 2–3. The results also contained an old DS Smith directory entry, which the
   agent selected for operating. It is incorrect to say that search never found the label's
   source in those trials.

Sprenger and AMR are excluded labels and do not contribute to the 159 scored comparisons.
The search-depth experiment demonstrates better page retrieval, not a better final agent
score: the pipeline was not rerun with those settings. It changed `search_depth` and
`max_results`, not the subscription plan. It does not establish that buying another plan
alone fixes the problem.

## Eight failure groups: attribution and limits

The search column means evidence from these runs or controls, not that search could
theoretically matter. The model column means an existing instruction was violated, not that
a stronger model is a proven remedy.

| # | Group | Rule problem | Existing instruction violated | Needed HTML evidence missing from search |
|---|---|---|---|---|
| 1 | identified_type | Yes: type boundaries and planning-area mappings; clarified in 10.8 | Yes: chemical production despite the plant definition; F10 after an explicit Kerngebiet rule | Yes: Wiesendamm and the Sprenger/AMR controls |
| 2 | status | Yes: default operating in triage; also the constraint that an address page without a plan number is ineligible | Yes: operation inferred from a rental offer, or a suitable status source ignored | Not established as an isolated cause in the failing trials |
| 3 | evidence_id / key_facts | No separate missing rule established | Yes: F12 quotes a web page with evidence_id=null; FMB cites a page without the required address match | Not established |
| 4 | Search and stopping | The rule permits stopping when further search seems unlikely to help, without an additional check; clearer criteria are a candidate, not a measured fix | No unambiguous stopping-rule violation established: the instruction permits that judgment | Yes: controlled depth/max_results comparisons |
| 5 | Report distorts supplied facts | No separate missing rule established | Yes: 30 m becomes inside the plan; a supplied legal status is described as absent | Not established |
| 6 | Claims exceed the evidence's scope | Finding, report rules and rubrics need consistent scope: plot / whole plan, existing buildings / new development, map name / confirmed operator | A separate report-model violation is not established for all flags: planned explicitly meant building not started, and existing buildings were already in key_facts | Not established |
| 7 | Effects on neighbours | Observed flags depend on the assigned type and its assessment; see group 1 | Classification errors can propagate; no separate report instruction violation confirmed for these effect flags | Not established |
| 8 | Uncited report claims | The rule already required starting with the first object and citing claims about it | Yes: the uncited E1 introduction | Not established |

### Axis 4 applied to the same eight groups

This table records options and decisions; the MVP chose among them by 2026-10-21, see the
proposals below. Unselected options are not scheduled changes or
measured fixes. A possible intervention does not establish that the existing constraint
caused a particular fail.

| # | Group | Candidate execution change | Evidence and limits |
|---|---|---|---|
| 1 | identified_type | Pass and validate decision evidence; consider allowing several sources | A finding currently rests on one web page and the object's data. This limit has not been isolated as a cause of type errors |
| 2 | status | Represent type and status evidence separately, and distinguish a part from the whole site | Scope problems occurred. A new representation needs testing and still requires a sound status rule |
| 3 | evidence_id / key_facts | Give grounding errors back to the model for a bounded correction attempt | The current check immediately replaces a failed finding with unidentified. F12 shows a citation/source mismatch; successful correction by retry is untested |
| 4 | Search and stopping | Change the search/extract budget; provide a further query or HTML read when evidence is missing | CURVE and Wiesendamm stopped after one search with a cap of 3. Raising the cap alone does not address that observed stopping mechanism |
| 5 | Report distorts supplied facts | No execution change selected for this MVP fix | Use effort first, then a targeted report-prompt change if factual distortions remain. Code rendering and new report validators are excluded from this fix |
| 6 | Claims exceed the evidence's scope | Declined for the MVP: separate subject/area/time fields for each fact and a new Finding/report consistency checker | The extra state and validation work have no demonstrated need. Use step 10.9: try effort first, then clarify the existing prompt where the first wrong generalization occurs if needed. Some flags already came from the Finding or the rules; a weak model is not established as their sole cause |
| 7 | Effects on neighbours | No separate report execution change selected | Trace the first failing step: the observed report effects followed the assigned types. Fix classification through 10.9–10.10 where the type was wrong; review the evaluation where its type assessment was wrong. A coded effect mapping would not repair these causes |
| 8 | Uncited report claims | No execution change selected for this MVP fix: object-specific blocks with required references and a separate check of unattached claims are excluded | Code already checks valid IDs and coverage of every object, but not support for every claim. The uncited introduction passed that guard. Use effort first, then a targeted report-prompt change if missing citations remain, as in priority row 7 |

### Current execution constraints

- **TOOL_CAP=3 counts search and extract together per investigation**, not three searches
  plus page reads. At the cap, code goes straight to drafting the finding. The cap can
  matter, but its contribution to the current failures has not been measured separately.
- **Early stopping is different from exhausting the budget.** All three Wiesendamm and
  all three CURVE trials stopped after one search. For CURVE, the correct URL was present,
  the snippet lacked the facts, and extract was not called. More permitted calls alone do
  not address this.
- Older plan investigations spent calls reading PDFs. Step 10.8 already removed reading
  PDFs linked from WFS plan data. Do not present this as a new unresolved HTML-search fault.
- **One web page plus the object's data** is the finding contract. Type evidence on one
  page and status evidence on another may require a contract change to combine them.
  This is a possible constraint, not the established cause of all unknown statuses.
- **PAGE_CHARS=40000:** longer text is cut with a warning to the model. The reviewed errors
  do not establish loss of a decisive fact through this truncation. CURVE's short search
  snippet is a different mechanism.
- The report receives objects and Findings with key_facts, not every retrieved page.
  An incorrect or incomplete Finding can therefore propagate even if the report model
  follows its instructions. Diagnose the first failing stage.
- A grounding failure has no finding-correction retry. Report retries exist, but respond to
  invalid references or missing objects, not every semantic error or unsupported sentence.

## Evaluation quality

An incorrect label, a disputed meaning of status, or an inconsistent rubric can produce a
fail while the agent follows its contract. Resolve these by the intended meaning and
evidence, not by the desire for a higher pass rate. Labels also measure real-world truth,
so a known contract limitation can legitimately remain an error against a reachable label.

This is observed, not just hypothetical: the full-run scores changed after label corrections
and plan exclusions. V-13 was relabelled commercial. Some effect flags depended on the type
passed to the report and its assessment, not on an independent report-model violation.
Plan generalizations require agreement on status semantics, reporting rules and rubrics.

## How to use this audit

1. Check the label and agent version for each fail, then locate the first failing stage.
   Do not count the same error repeated in the report as a new root cause.
2. Compare models and prompts on the same saved inputs. Attribute an instruction violation
   only when both the applicable rule and sufficient evidence were in the actual context.
3. Trace search as query → URL → returned text → extract → used fact. Distinguish a missing
   page, a missing snippet fact, a poor source choice and a stop with budget remaining.
4. Change one factor at a time: rules, model/effort, depth/max_results or execution design.
   After component checks, measure E2E quality, cost and time. Finding the page is not yet
   successful classification, and successful classification is not yet a correct report.

This is a basis for choosing work, not an approved implementation plan. No model/effort,
tool-budget or full-pipeline wider-search comparison was run for this audit. The architecture
candidates above are not implemented or added to the roadmap.

## Readiness and proposed priorities

**The audit is ready to guide implementation experiments.** Another broad investigation is
not needed before starting step 10.9. It is not evidence that every proposed fix works, nor
that every historical failure remains after 10.8. Keep the diagnosis here; promote only
chosen interventions into the roadmap. Record experiment outcomes alongside their runs,
then update this audit's conclusions when the evidence changes.

The proposals below were decided for the MVP by 2026-10-21; the paragraph after the table
says how. The order is a recommendation, not a new commitment to implement every row. Effort estimates are relative engineering effort, not measured
runtime cost. Expected benefit means a plausible target supported by the audit, not a
predicted percentage gain.

| Order | Intervention | Engineering effort / expected benefit | Smallest useful check |
|---|---|---|---|
| 1 | Step 10.9: compare default, high and extra-high effort on the finding and Enough suites and on fixed report inputs, keeping prompts and evidence fixed | Small change, potentially broad benefit to rule execution; a cheap diagnostic where evidence and an existing rule are already sufficient. Runtime cost may rise | Three trials per task or saved report input; type/status, grounding, stopping, claim scope, report fidelity and citation placement separately, plus cost and time. Replay the same report inputs at each effort, with passing controls; inspect flags for actual changes of fact, not equivalent wording. The finding suite drafts a finding from fixed pages and cannot see a stop such as CURVE's or Wiesendamm's. Build Enough N1–N6 as now specified in the evaluation architecture. With cap still 3, compare decisions from fixed histories: insufficient snippet → read; evidence already sufficient → stop; irrelevant page → no forced read. A read passes only as an extract call of that page's URL, not as any tool call. A same-input comparison with one stronger model remains an unselected candidate for residual finding or stopping violations, not a commitment in 10.9 |
| 2 | Step 10.10: a consistent classification decision order, with a separate status decision | Medium effort, broad potential because type errors also propagate into effects and report wording | Compare with the current prompts at the selected effort. Keep type meanings and evidence requirements; use general rules and new examples, not addresses from E1–E5 |
| 3 | One bounded correction attempt after a grounding rejection | Small to medium effort, narrow potential to recover evidence-format failures; extra model calls only on rejection | Retry on the same evidence with the exact validation errors, then validate again. Keep unidentified when evidence is insufficient; do not recover a case merely by weakening the check |
| 4 | Make the next search action explicit when an eligible HTML result looks relevant but its snippet lacks the needed facts | Small prompt change; directly targets unused extract calls, such as CURVE. Benefit is confined to investigations with a useful next step | Only if the Enough read case still fails at the effort chosen in row 1: the same Enough tasks, then selected live investigations |
| 5 | Test wider/deeper search in the investigation, not just page retrieval | Small configuration change, potentially useful for missed HTML sources; more checker calls and larger context increase total cost | Use the existing spike as motivation. Compare basic/5 with basic/20, then basic/20 with advanced/20 while other settings stay fixed. Measure final findings as well as page recall; keep excluded labels out of the baseline score |
| 6 | Review status rules that permit a wrong answer: map-default operating, stale directories, and a plot treated as a whole plan | Medium effort; directly relevant to observed status errors, but requires decisions about acceptable evidence rather than stronger wording alone | Agree the rule first. Contrast current operation / old evidence / unknown, and whole-site / one-plot evidence. Align the existing triage, finding and report prompts and the rubric before applying it; this is a rule review, not a new runtime consistency checker |
| 7 | Step 10.9: try effort first for report fact distortions and missing citations; if they remain, clarify only the report prompt as needed | Small scope, targets report errors while keeping the architecture; benefit is unmeasured | At each effort, replay fixed saved report inputs with passing controls. If errors remain at the selected effort, refine the prompt with general rules and replay the same inputs. Preserve distances, inside/outside meaning, legal status and the scope of supplied facts; check citation placement, including uncited introductions. Plain-language paraphrases are acceptable. No coded rendering or new report validators for this fix |

Rows 1–2 and the report effort/prompt sequence in row 7 are represented by 10.9–10.10, and
row 4 by 10.10, since the Enough read case still failed at the effort selected in 10.9. On
2026-10-21 row 4 was dropped for the MVP, and the labels that need it, a deeper search or a
check of railway status are left out (see the eval architecture). Row 3 joined 10.10 after
its full run of 2026-10-21, where a key fact with a changed word ending was rejected, and the
retry covers an answer without the Finding tool too.
The separate status-policy review in row 6 is broader than ordering the existing
classification rules. Rows 5 and 6 are not planned: the MVP ends the eval work, and the
limits they address are listed in the
[MVP eval results](2026-10-21-mvp-eval-results.md#known-limitations).

### Conditions for trusting the comparison

- Record the code revision, agent model and effort, prompt version, tool budget and search
  settings. Keep judge model, effort and calibrated rubric fixed when comparing agent
  models. Since step 10.9 `JUDGE_MODEL` has its own default and no longer falls back to `MODEL`,
  so changing the agent does not silently change its evaluator. The calibration gate refuses a
  judge model or effort other than the calibrated one, but only on report and end-to-end runs;
  the other component runs have no judge to change. The agent's effort does not touch the judges.
- First use component inputs to isolate the intervention; retain the tasks that currently
  pass as controls. Add a task only for a failure mechanism that no current task covers.
  Include unfamiliar examples and negative cases: an order that always chooses a more
  hazardous type is not an improvement.
- Record wrong claims, unidentified outcomes and unknown statuses separately. Fewer false
  assertions obtained by making everything unknown is a coverage tradeoff, not a general
  quality gain. A page found or an extra call used is not itself a successful finding.
- For a promising change, require a repeated improvement, not one fortunate answer. Use
  the roadmap's two-of-three criterion for a changed E2E label as an operational signal,
  not statistical proof. Inspect new regressions rather than hiding them in the total.
- Compare live-search variants close together and retain their returned text: live data and
  queries vary. Keep failed address lookups visible. Sprenger/AMR retrieval improvements
  belong in a separate diagnostic result while those labels remain excluded.
- Count all added work. Each search result has its own injection-check call; 20 instead of
  5 results can raise checking and prompt costs even without more search calls. Reflect any
  changed search depth in cost accounting before claiming a cost/quality improvement.
- Use the already planned full E1–E5 run after 10.9–10.10 to check the combined result;
  component comparisons supply the attribution. Do not run the whole suite after every
  wording edit. If a later search or architecture change is selected, validate its final
  pipeline too. For this demo MVP, prioritize observed quality; record cost and time for the
  results without adding a separate cost-optimization task.

### Defer unless new evidence makes the case

- **A higher tool cap by itself:** first show failed investigations that exhaust all calls
  and still have a useful next action. The one-call CURVE/Wiesendamm stops do not justify it.
- **Multiple sources per finding or a new orchestration design:**
  these affect evidence semantics, citations and graders. First demonstrate residual
  failures that the current contract prevents solving. The one-page rule also protects
  against mixing different businesses' facts; removing it has a real tradeoff.
- **Another search provider or subscription plan:** test available depth/results settings
  and extraction first. The current evidence does not require a provider migration.
- **More prompt text everywhere, repeated self-review, or a stronger model everywhere:**
  target a demonstrated failure and measure it. Do not build model routing merely to avoid
  the initial fixed-input comparison.
- **Report-only effect fixes for upstream type errors:** fix classification first. A
  deterministic effect mapping cannot repair a wrong type.
- **Reopening linked-plan PDF support or redoing completed 10.8 fixes:** outside this
  improvement batch. Nor should honest unknowns be turned into guesses to chase 100%.

The stopping point is a measured, useful improvement with documented residual limits,
not the elimination of every fail. After the planned batch, continue only where a remaining
mechanism has a concrete affordable intervention. Otherwise record it as a limitation and
finish the MVP. No exact return-on-effort ranking is proven until these comparisons run.

## Step 10.9 results, 2026-10-20

The same code, prompts and inputs at each effort, three trials each; the default effort of
Haiku 5.5 is medium. The judges stayed at their calibrated extra-high effort.

| | Medium (default) | High | Extra-high |
|---|---|---|---|
| Finding F1, F2 and F4–F15, trials passed | 41 of 42 | 42 of 42 | 38 of 42, three without a finding |
| Enough N1–N6, trials passed | 17 of 18 | 13 of 18 | 14 of 18 |
| Report replay, statements flagged by the support judge | 23 of 259 | 22 of 265 | 14 of 202 |
| Report replay, interpretation fails | 4, and 1 judge error, of 21 | 0 of 21 | 2 of 17 |
| Reports failed at 16,000 output tokens | 0 of 21 | 0 of 21 | 4 of 21 |
| One report: time, cost | 21 s, $0.003 | 32 s, $0.005 | 74 s, $0.010 |
| Finding suite: time, cost | 2.8 min, $0.033 | 3.7 min, $0.040 | 5.8 min, $0.056 |

- **Selected: high.** Extra-high did not do clearly better, and it failed in two ways that
  stop a full run: a finding answer without the Finding tool, and a report cut off at its
  output tokens in both attempts. It is also about twice as slow and costly as high. At high
  the triage and input loop suites pass every trial, 6 of 6 and 9 of 9.
- **Enough at high** fails by extra reads where the evidence already sufficed (N1, N3): an
  extra call, not a wrong finding. The CURVE case, N5, passes 2 of 3 at medium and at high, so
  effort does not settle the read of a page whose snippet lacks the facts.
- **Report inputs:** the four failing reports of 18 October (E1 trial 1, E2 trials 1–2, E5
  trial 1) and three passing controls (E2, E3 and E5, trial 3 each). The 30 m inside-the-plan
  distortion and the uncited E1 introduction did not recur at any effort; at medium, one E1
  report put a railway 67 m away right next to the property.
- **Two report errors remained at every effort**, and the report prompt now has a general rule
  for each:
  - A plan's legal status described as not given, although its data give it. The message's
    "status not given" is the finding's status, whether building has started, and the model
    took it for the legal status. At high, 3 of the 6 trials of the E5 inputs before; none
    after.
  - Statements without a citation: a sentence about several objects, or an effect after the
    citation. 6 in two high trials before; none after.
  - At high with the clarified prompt: 13 of 258 statements flagged; interpretation 1 fail and
    1 judge error, no verdict 1 fail, of 21.
- **The flags left follow the input Findings**, as in group 7: an operator or a status taken
  from a page that does not name the object's address (FMB, the former Philip Morris works),
  and the Finding's type (a maker of chemicals as production; a residential plan whose type
  shows no effect, which the report then says, and the no-verdict judge once read as
  reassurance). They belong to rows 2 and 6, not to the report prompt.
- Cost about $2.10 in all, judges included; about two hours of runs, with the three efforts
  in parallel.

## Corrections to earlier interpretations

- Do not mark every group as a prompt defect merely because more instructions might help.
  The necessary rules already existed for groups 3, 5 and 8.
- Do not call early stopping an instruction violation just because a better next search
  was possible. The instruction allowed stopping when further search seemed unhelpful.
- All three support flags about effects need their input Findings considered: Pumpwerk
  Stralau already had wastewater plant, and V-13 and XV-19 had commercial. The report used
  those types' effects. V-13 was subsequently settled as commercial. These are not three
  independent report instruction violations.
- F12's web quote exists in the returned page. Its error is using that quote with
  evidence_id=null, not inventing or paraphrasing the quote.
- A stronger model has not been tested. Instruction violations justify a comparison,
  not a promise that another model will solve them.

## Evidence and code references

Raw eval runs stay local in the ignored `evals/results/` directory, since they hold the pages
the agent read. The run files are named below for provenance.
Code links show the checkout's version; the execution review used `7005abe`.

- [Search control findings](../../spikes/search-depth/findings-2026-10-16.md)
- [Search control script](../../spikes/search-depth/spike.py)
- E1, three trials (`2026-10-18T18-11-27-679981Z.jsonl`)
- E2–E5, three trials (`2026-10-18T18-29-57-344038Z.jsonl`)
- F12 grounding run (`2026-10-19T00-17-45-422034Z.jsonl`)
- F10 after the explicit rule (`2026-10-19T00-12-48-377180Z.jsonl`)
- Step 10.9, finding at medium, high and extra-high:
  medium (`2026-10-20T17-03-08-002408Z.jsonl`),
  high (`2026-10-20T17-03-08-209948Z.jsonl`),
  extra-high (`2026-10-20T17-03-08-235563Z.jsonl`)
- Step 10.9, Enough: medium (`2026-10-20T17-06-00-183067Z.jsonl`),
  high (`2026-10-20T17-06-57-909735Z.jsonl`),
  extra-high (`2026-10-20T17-09-02-214176Z.jsonl`)
- Step 10.9, report replay:
  medium (`2026-10-20T17-08-24-008008Z-replay.jsonl`),
  high (`2026-10-20T17-08-24-157131Z-replay.jsonl`),
  extra-high (`2026-10-20T17-11-36-236296Z-replay.jsonl`),
  high with the clarified prompt (`2026-10-20T18-30-58-177959Z-replay.jsonl`)
- Step 10.9, controls at high: triage (`2026-10-20T18-10-44-513659Z.jsonl`),
  input loop (`2026-10-20T18-11-05-753610Z.jsonl`)
- [Settings and limits](../../src/out_of_frame/config.py)
- [Investigation loop, truncation and grounding fallback](../../src/out_of_frame/investigation.py)
- [Single-page evidence and quote validation](../../src/out_of_frame/grounding.py)
- [Tavily wrapper](../../src/out_of_frame/web_search.py)
- [Passing Findings and sources](../../src/out_of_frame/agent.py)
- [Investigation prompt](../../src/out_of_frame/prompts/investigation.md.j2)
- [Report rules](../../src/out_of_frame/prompts/report.md.j2)
- [Report checks and rendering](../../src/out_of_frame/report.py)
- [Evaluation architecture](../eval-architecture.md)
- [Roadmap and completed 10.8 changes](../roadmap.md)
- Baseline prompts were inspected with
  `git show a7cea3b:src/out_of_frame/prompts/...`.

The current-code review does not mean that historical E1–E5 trials were rerun on that code.
