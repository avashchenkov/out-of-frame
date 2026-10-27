# Roadmap

The steps to the MVP, and the demo after it, in the order they were done. Each step names
its result and its checks.

1. ✅ **Repository setup.**
2. ✅ **Research scope.** Each checked category with its radius and its source. Kept as
   data.
3. ✅ **Spike.** How many objects of each category does Overpass return, and how many have no
   name? This sets the investigation cap per category.
4. ✅ **First eval cases and a minimal runner.** Prepare L1: one unnamed map object from a
   candidate end-to-end address, with a type and status verified from real-world evidence.
   Prepare F1: a written investigation state with no usable evidence and the tool cap reached,
   where the expected result is unidentified. Record the inputs, fixtures, evidence and dates;
   define the finding types, statuses and tool cap needed for these cases.
   Write L1's label by hand from its recorded map response: the labelling script needs the
   grouping code of step 6.
   States follow the [logical state model](architecture.md#the-state), not LangGraph classes.
   Build only enough of `run(task)` to run and record these cases against a stub and grade
   their outcomes. Test each code grader on an outcome it must pass and one it must fail;
   put these tests and task-format checks in CI. This step is ready when both cases run and
   their expected outcomes can be distinguished from wrong ones. Other MVP cases come with
   the behaviour they check; the full task set is not a prerequisite for agent code.
5. ✅ **First working slice: investigate one object.** As a CLI: a precise address → one unclear
   map object → live Tavily search and page reads → a finding → a report with sources. Until
   triage in step 6, the CLI takes the nearest unnamed object of a checked category. All model
   calls use Claude Haiku 5.5; the evals show if it is not enough. In this order:
   1. ✅ The call that drafts the finding: its prompt and model call. Run F1 against it, and F5
      as a positive control: a prompt that never identifies anything also passes F1. The runner
      records an error of the part as a failed trial.
   2. ✅ The investigation subgraph in LangGraph ([ADR 1](adr/0001-langgraph.md)): search, the
      stopping decision, the tool cap, the finding, the grounding check and a web search
      failure. Code tests with a stubbed model and Tavily.
   3. ✅ Live Tavily. Run L1 on the live web; the harness counts the tool calls and the cost.
   4. ✅ The injection guards: prepare P1–P4 and F4, then build the checker.
   5. ✅ The CLI path: Nominatim, Overpass, the object choice and the report with sources. Check
      the whole path with replayed sources and a stubbed model.
   6. ✅ The rubrics of the three MVP judges, written with the first report. Run the judges
      uncalibrated; their scores are not quoted until they pass calibration in step 10.
   7. ✅ Fix what the hand grades of the first reports found wrong for the reader. The report
      names an object by what it is, never by its ID, and never as the nearest; it says how a
      type of object can affect people nearby, not how much or when, and leaves out opening
      hours and phone numbers. F7, from the Freiheit 22 pages whose right finding the grounding
      check rejected in 3 of 4 runs, passes at least 9 of 10 trials. If a sharper prompt cannot
      get there, the finding is written once more with the grounding errors.
   8. ✅ A finding rests on one page, the one that best settles the object, and on the object's
      own map data: every key fact comes from them, so that an object's citation stands for one
      page and the support judge gets only that page. Several businesses can share one site, and
      a live run gave one business another's facts from another page; one page keeps them
      apart. When the type and the status are on different pages, the status stays unknown.

   The result must demonstrate a supported finding and an honest unidentified outcome when
   evidence is missing; inspect the first report by hand.
6. ✅ **Several objects and triage.** Extend the path to every map category: grouping, the
   nearest five objects per category, code routing, triage and parallel investigations. The
   report must preserve clear findings, show unidentified and not investigated objects, and
   distinguish an empty result from a failure. To save time, the
   [labelling script](eval-architecture.md#ground-truth-labels), F2 and F6 move to step 10;
   R2–R4 are graded by code and read by hand, without the LLM judges; and a person reads one
   live report instead of filling in a hand-grade form. In this order:
   1. ✅ Types for every map category, each with one line on how such an object can affect
      people nearby; the report takes the effect from that line alone.
   2. ✅ The map: grouping, the nearest five per category, code routing (T3 as a code test), the
      addresses of the objects to investigate in one query, map objects replaced by ID, and
      parallel investigations, with page IDs unique across them and a limit on how many run
      at once. Code tests for grouping, distances, caps and failures.
   3. ✅ Triage: one call per remaining object, one at a time; a clear object gets a finding with
      the map's status, an unclear one goes to investigation within the cap. T1–T2.
   4. ✅ The report for many objects. From the first hand grades: it reads plainly; an object
      whose type alone shows no effect on people nearby, such as a cleaning business, gets one
      short line with its distance; it never quotes map tags such as landuse=industrial, and
      gives no details the reader cannot use, such as an object's map addresses. A draft that leaves out an
      object is written again. R2–R4.
   5. ✅ Live runs on Freiheit 22 and Corinthstraße 60; the person reads one report.
7. ✅ **Input conversation.** The first message can be any text: an address, a listing or a
   greeting. Add extraction, the address check, questions and LangGraph pauses, for the
   property's address only: where the user travels and when comes with the journeys in step 9.
   The user can resolve an ambiguous address; a precise Berlin address starts research without
   a question. The state is kept in memory: the graph saves it after each step and goes on
   from there when the user answers, but a run that stops is not continued once the process
   has ended. A known MVP limitation; the architecture allows a store on disk. In this order:
   1. ✅ The input loop: `messages`; the extract call, whose change code applies; the check by
      code, with the Nominatim response kept as a source; the question, which offers only the
      matches code found; a pause in memory for the answer; the CLI asks in the terminal. Code
      tests with a stubbed model and recorded Nominatim responses: applying changes, each
      reason to ask, and resuming the run.
   2. ✅ I2 in an input loop suite on recorded Nominatim responses; live runs from a listing and
      from an ambiguous address, and the person reads one conversation.
8. ✅ **Development plans.** Add the B-Plan WFS branch and feed its objects into the existing
   investigation. Check E4 with no commute destinations, plus code tests for filtering,
   distances, limits and source failure. The report must distinguish a plan's legal status
   from evidence about whether building has started, including when that status is unknown.
   A plan's finding uses the same types and statuses as a map object's. To save time, as in
   step 6, E4's label moves to step 10, and a person reads one live report. In this order:
   1. ✅ The plans: the square around the circle, the plans outside the circle dropped, the
      distance to the nearest edge, the nearest N, one object per plan with its legal status
      and content, and a plan source failure. Code tests on a recorded WFS response.
   2. ✅ The investigation of a plan: what the plan allows, and whether building has started.
   3. ✅ The report: a plan's legal status apart from whether building has started. A live run
      at an E4 candidate address, and the person reads one report.
9. ✅ **Commute.** Add Transitous journeys there and back. Test duration calculation, no route
   and unavailable outcomes; run the end-to-end cases with one and two destinations. The
   report must give the right destination, direction and duration, or the missing-route reason.
   From step 7: the input conversation asks where the user travels and when, a destination
   may be outside Berlin, and I1 and I3 check it. In this order:
   1. ✅ The input: `destinations`. The extract call gives null for no change, an empty list for
      nowhere, or the whole new list with the ID of each destination it keeps; code gives a new
      one its ID. Code geocodes each destination's address as one building, like the
      property's, but anywhere: without the added "Berlin", the Berlin filter or "Berlin" in
      the places it offers. Code finds everything missing at once: the property, where the user
      travels, a destination's address and both of its times. Nominatim gets at most one
      request a second. Code tests with a stubbed model and recorded Nominatim responses; I2
      and the pipeline tests get a user who travels nowhere. I1 and I3 in the input loop suite,
      whose grader also checks the destinations and their times, and the person reads one
      conversation.
   2. ✅ The journeys: the commute branch, a third research start next to the map and the plans.
      Code plans them on the first Wednesday after the date that is neither a public holiday
      nor 24 or 31 December, at the user's times in Berlin's time zone; Wednesday is never a
      movable holiday. Each journey is the mean of the first three connections that leave at
      the user's time or later, or of fewer. No walk is asked for as a direct route, since
      Transitous then drops the connections slower than it. No connection is no route; a failed
      request makes its journey unavailable and adds transit to `failures`, which the CLI
      tells. The User-Agent names the version, as Transitous asks. Code tests on recorded
      Transitous responses: the mean, no route and unavailable.
   3. ✅ The report: code adds the journeys after the model's text, each with its destination,
      direction and duration, or why it has none, and the link to the Transitous sources if
      there are journeys; the model no longer reads transit in `failures`. Code tests; live
      runs with one and two destinations, and the person reads one report.
10. ✅ **Judge calibration and MVP results.** Calibrate the three MVP judges against human grades
    of the first real outputs and deliberately faulty examples. Complete and run every
    [MVP task](eval-architecture.md#mvp), several trials each; check that the labels cover
    every category. Publish results with failures and limitations.
    From the first hand grades: the support rubric counts an effect on a resident, such as
    traffic, as backed only when the type's line or the cited page gives it, and the
    interpretation rubric only when the type's line gives its kind; the person checks the
    grades of evals/calibration/ against the changed rubrics.
    From step 6: the labelling script, F2 and F6; the support rubric grades a triage finding by
    its map data, like any other, since triage settles only what the map makes clear; the
    interpretation rubric lets an object whose type alone shows no
    effect have one short sentence, as the report prompt asks since step 6.4. A known
    limitation to publish: a site that several businesses share gets the type of the business
    that the investigation finds. At Klärwerkstraße 1 and 1a, runs found a cleaning business
    and a Jobcenter project, both commercial, and missed a metalwork shop with production halls
    there. From the live runs of step 6.5: a finding can cite a page that does not back its type
    or status, such as an Impressum with an address only, or cite the map though a page it read
    settles the status, so that a running S-Bahn line reads as "unknown whether in use".
    From step 7: the report can still call an object of type other harmless, such as "its type
    alone does not show any effect" for a sewage pumping station. From step 8: E4's label, at
    Teutonenstraße 10, 12524 Berlin: plan XV-25-1, in procedure; the district's press release of
    2026-08-06 names it and an unused plot at Germanenstraße 2/6 for housing,
    https://www.berlin.de/ba-treptow-koepenick/aktuelles/pressemitteilungen/2026/pressemitteilung.1700019.php.
    From step 9: the support rubric's TODOs for B-Plans and journeys go with calibration; code
    adds the journeys after the draft, so no judge grades them. From the live report at
    Teutonenstraße 10: the report explained that building had not started on XV-25-1 by its
    legal status ("because the plan is only planned"), against its own rule; it called
    CURVE-Campus an office site, though its page also names manufacturing and a TV studio; and
    it said what a plan in procedure allows, where the finding prompt says what it is meant to
    allow, so "XV-25-1 allows housing" reads as a permission. In this order:
    1. ✅ The rubrics, before anything is graded, and two fixes of the report prompt they
       need.
       - Support: the type's line backs a general effect of that type; a specific one, such as
         how often, needs the cited page. Map data back the status their tags show, as triage
         reads them, so a triage finding is graded like any other. A plan's WFS fields back its
         legal status and, where they name it, what it is meant to allow, never whether
         building has started; a plan in procedure is only meant to allow its uses.
       - Interpretation, which sees no pages: an identified object needs a meaning only if its
         type's line gives an effect, and one whose type shows none may have one short
         sentence. A meaning fits only if it is of the kind the type's line gives; calling an
         object of type other harmless is a no, and so is giving a plan's legal status as the
         reason that building has or has not started.
       - Both judges' templates mark a plan as one, as the report prompt does. The journeys,
         B-Plan and question TODOs go: no judge grades journeys or questions in the MVP.
       - The report prompt says what a plan in procedure is meant to allow, not what it allows,
         and never that the type of an object of type other shows no effect.
       - The person checks the grades of evals/calibration/ against the changed rubrics.
    2. ✅ The end-to-end tasks, E1–E5, with their labels.
       - First the task format: an end-to-end suite with its messages, the expected input as in
         the input loop, the expected outcome of each journey, and a list of labels, each with
         its object ID and category, or marked as left out with the reason.
       - The labelling script records the Overpass and WFS responses at an address as fixtures
         and writes a label for each object the agent can see there: the nearest N per category
         and the nearest N plans, both 5 by default, with the ID, category, coordinates and
         tolerance from the agent's own code.
       - The addresses: E1 at Freiheit 22 with one destination, E4 at Teutonenstraße 10 with
         two, and E2, E3 and E5 at the candidates of the eval architecture, where the user
         travels nowhere. The property and each destination geocode to one building, and each
         first message completes the input, so the judges grade only reports. As soon as the
         script lists an address's objects, the object it is chosen for must be among them; if
         not, the next candidate is tried.
       - Labels as the [eval architecture](eval-architecture.md#ground-truth-labels) says:
         Claude proposes each type, status and page, with the Tavily search that finds it; a
         new Claude session, Codex and Grok each check them without seeing the others' checks;
         the person settles each point the checkers disagree on. E4's label in the note above
         is a proposal like any other. While labelling E2, Claude also keeps the pages that F2
         and F6 need.
       - Code grades the input, the findings against the labels and the journeys, as the eval
         architecture says. Grader tests; in CI, the task format, and every category has a
         scored label at one address at least.
    3. ✅ F2 and F6 in the finding suite, from the pages kept in 10.2, rewritten in new words.
       The pages are kept in local results, evals/results/pages-10-2, read on 2026-10-16. F2,
       at the former Philip Morris factory: PMI's undated list of affiliates still gives Philip
       Morris Manufacturing GmbH at Neuköllnische Allee 80, a news page says production there
       is to end in the first half of 2025, and a directory entry at the address, written for
       the task after a report of the last production day, says it closed on 30 June 2025: no
       real page gives the closure with the address, and the report that names the Berlin plant
       also says that tax stamps are still printed there. F6,
       at the stormwater filter of E5: only a page of the Berliner Wasserbetriebe about the
       Retentionsbodenfilter in Blankenburg, elsewhere, so the finding rests on the map data.
    4. ✅ The end-to-end suite in evals/run.py: the whole agent on live sources from the task's
       messages, each run saved as evals/judge.py saves it and graded by code at once; no judge
       grades it before calibration. The fixed component suites report pass@k and pass^k
       averaged over their tasks; the live investigation and end-to-end suites report their own
       metrics, as the eval architecture lists. One trial of each task gives the first real
       outputs.
    5. ✅ Calibration, by the rules of the [eval architecture](eval-architecture.md#llm-judges).
       Each judge's set takes examples from these outputs and from the saved runs of the
       earlier steps, plus faulty ones made on purpose, on top of them: at least one for each
       question the judge answers, and the report failures noted above that the trials do not
       show. About fifteen statements for support, with supported, unsupported and contradicted
       at least once each, and eight reports each for interpretation and no verdict, the same
       reports for both. A Claude session and Codex grade them apart on a form, each example as
       the judge sees it, and the person settles what they disagree on; only then do the judges
       run on them, and a script checks each judge version against the grades. A judge that
       still fails after two changes of its rubric is left out, with its axis.
    6. ✅ Fix what the person found wrong for the reader, reading the five reports of 10.4 as
       a user does. "A development plan is 190 m away" reads as a paper at that distance: the
       report says instead that the land at that distance has a development plan. What such a
       plan is, the city's rules for what may be built there, code adds once after the draft,
       as it adds what the report covers, so no judge grades a definition. Code keeps each
       distance exact and rounds it to whole metres wherever it is shown; the prompt reads 0 m
       as the property lying in the object's area, such as a plan or the industrial area around
       it, or right next to it. A plan that could not be identified goes at the end, like any
       such object. The distance check and the support and interpretation rubrics accept that
       wording, and both judges are calibrated again. A judge's answers varied from one check
       to the next on the same prompts, so the check now asks three times and counts an answer
       as agreeing only if every trial gives it, and every judge is checked again. The person
       settled what the judges then disagreed on: a company's name with the city alone, such as
       its Berlin plant, does not name a site, in the finding prompt as in the support rubric,
       and three rubric lines say what the graders had meant. The faults the judges still
       missed in one trial of three were lapses of attention, so they think at xhigh effort,
       recorded with their model. Code tests; live runs at E2 and E4, where the property lies in
       a plan's area, with the three judges run on them, and the person reads one report.
    7. ✅ The full run: every MVP task, three trials each.
       - A judge runs only if the calibration script has recorded that its version passed,
         with the judge model and effort of the run, the set as it is now and the prompts its
         examples were stamped with, which need the saved runs in local results. evals/run.py
         and evals/judge.py check this once at the start, before any paid call, and stop with
         the judge and the reason if a version does not match: every judge has passed, so a
         mismatch is an accident, not a judge to leave out.
       - In evals/run.py, the support judge grades each statement of an end-to-end report, and
         the interpretation and no verdict judges grade each report of the end-to-end and the
         report suites; a report task's grades go with its trial, and an end-to-end trial's are
         saved next to its run, as evals/judge.py saves them. A report task passes only if
         neither finds something wrong. An answer of unknown, or a judge's answer that was cut
         off or does not parse, does not fail it, and each suite counts them next to its
         scores; any other error of a judge stops the eval run, as a grader's error does. An
         end-to-end task reports the share of statements found unsupported or contradicted
         among those graded supported, unsupported or contradicted, with the unknown ones and
         the errors apart, and how many of its reports each of the other two judges passed.
         The judges run after the agent and their cost is counted apart, at the judge model's
         price.
       - The end-to-end suite shows the query for the addresses of the objects to investigate
         next to the research branches, as failed when Overpass failed on it: the objects are
         then investigated without addresses, and nothing is added to `failures`, so a trial
         graded on its state alone does not show it. The public Overpass instance failed on
         it when it was busy, in the evening, so the end-to-end runs try each call to a source
         five times, a run setting.
       - Code tests; then every suite with its part, three trials per task: first the component
         suites, then one end-to-end task, then the others. Claude sorted each failure by its
         cause, the agent, a label or a judge, and Codex gave a second opinion. Three labels
         contradicted the agent's own rules: two E2 sites without a type had a status, which no
         finding can give, so their status is null now; plan 5-1VE needs a page about the
         address that its own data name, which the finding prompt does not count, a known
         limitation of 8. The person settled the arguable labels by their evidence: V-13 is
         commercial, for its core area; XV-19, XV-23 and Bergiusstraße 21 stay. The judges'
         findings were the agent's faults. The runs stay the baseline, graded again by code
         against the changed labels.
    8. ✅ Fix the largest general failures of the full run, each by a rule that holds at any
       address, never for one task. Before each change, Claude reads the failing runs for the
       cause, and the person settles the change. The rules go into the agent's prompts, not
       into the types of the research scope, which every judge's set is checked against. In
       this order:
       - The investigation of a plan reads none of the PDFs that its WFS data link, neither the
         scan of its drawing nor its reasons: most reads of them returned no page, each used one
         of the investigation's tool calls, and the reasons that were read were cut and gave uses
         where the plan sets none. A PDF that a search finds, such as a press release, it still
         reads. Its type comes from its WFS data, by the rules below, or, for a plan without
         them, from a page about it; where its data name its uses, it searches only for whether
         building has started. That settles every plan label but three. Only their reasons show
         XIV-182's petrol station and that V-18's railway is copied in from railway law: both
         are left out, as the eval architecture says of a label that the agent cannot reach, and
         the baseline is graded again. XV-51j is a known limitation below.
       - A plan's type by its kind of area, written out in the finding prompt: a housing area
         and a mixed area (Mischgebiet) are other, since a mixed area allows only businesses
         that do not much disturb homes; a core area (Kerngebiet) is commercial, as for V-13; and
         a business area with no use named stays without a type. The person settled the mixed
         area.
       - An offer of a site for rent or sale alone does not show what the site is used for; what
         such a page says about the tenants there now does. A site that makes chemicals is a
         plant, not production; a wholesaler that keeps goods in stock is logistics, not
         commercial; and a page that shows a business of the plant type, such as a fuel depot, at
         one of the object's addresses makes the site a plant: the types already say so.
       Each rule first gets fixed-data tasks, as the eval architecture asks: finding tasks of
       plans from their WFS data, one per kind of area above, and finding tasks from the pages
       that the full run read, rewritten in new words, for the rules on offers, chemicals,
       wholesalers and a business of the plant type at a site's address. After each change these
       run, and the component suites, which must still pass. Then, with the labels that each
       change should turn written down first, one full run of E1–E5, three trials each, on one
       day, graded label by label against the full run of 7, which stays the baseline: the wrong
       claims apart from the objects left unidentified, the trials whose address query failed
       marked on both sides, the judges' counts next to those of 7, the reads of a plan's linked
       PDFs, which should be none, and a label counted as turned only when it changes in two
       trials of three at least. Known limitations, not fixed: whether trains still run on a line
       that the map tags as in use, since triage takes its status from the tags; a map tag that
       is wrong for an object with no address and a name that points at no one site, such as a
       rainwater filter tagged as a wastewater plant; a site that several businesses share; an
       unnamed site whose page the agent's searches miss; a page out of date, or one that gives
       a site's planned uses as current; a use that only a plan's documents name; a plan
       replaced in part by another, such as XV-51j; and a plan whose state shows only on a page
       about the one plot that its data name, such as 5-1VE, since counting such a page would
       change the support rubric and need its calibration again. Done: the prompts, the labels
       left out and the fixed-data tasks; the component suites pass, and the new tasks pass in
       most trials, not all. The full run of E1–E5 waits for 9 and 10, so that one run
       measures 8 to 10 against the baseline, with the predictions written down again first.
    9. ✅ The agent's model calls at the effort that the evals show best: high, unless
       extra-high does clearly better. Its findings were unstable from trial to trial where a
       page settled the object but a rule was applied one way or another, in the full run of 7
       and the component runs of 8, and the judges grew stable at the extra-high effort in their
       calibration. Three settings, each a model, an
       effort and output tokens: the judges', the agent's and the injection check's. The agent's
       calls, from the input conversation and triage to the finding and the report, run at the
       selected effort; the injection check stays at the default effort, since it is a
       classifier that runs on every snippet and page, apart from the agent's reasoning. First
       the Enough suite is built, N1–N6, as the
       [quality audit](evals/2026-10-19-agent-quality-audit.md) asks: the finding suite starts
       from fixed pages, so it cannot show a search that stops before
       reading a page whose snippet lacks the facts. Then the finding and Enough suites
       at the default effort, which is medium on Haiku 5.5, high and extra-high, and the
       effort that they show best: high, unless extra-high does clearly better for its cost
       and time, as Anthropic advises extra-high on Haiku 5.5 only where the evals show a gain.
       The cost and the time of a run are counted with it. A stronger model, Sonnet 5.5, is a
       candidate only if no effort does well enough, and is not part of this step. The triage
       and input loop suites run at the selected effort as controls and must still pass. At
       each effort, also replay fixed report inputs from saved runs, locally, since a saved run
       holds the pages it read and is not committed as a task, with passing reports as
       controls: check distances, inside/outside claims, legal status and citations, including
       an uncited introduction. Where facts were still distorted, only the report prompt was
       made clearer. Separate fields for the subject, area and time of each fact, and a new
       check of the report against the findings, were rejected for the MVP: nothing showed a
       need for them.
    10. ✅ A classification funnel: the type of an object or a plan settled by questions in a
       fixed order, from what can affect people nearby the most to the least, in place of the
       special rules added one by one. The status decision stays separate from this type
       funnel. Before any code: where the type is decided
       now (the triage, investigation and finding prompts, the research scope's types, the
       judges' rubrics), and which of the special rules no task checks yet, such as a shop on
       a wholesaler's site. Each such rule gets a negative control task first, built as the
       eval architecture says, so that the funnel cannot lose it unseen. Then a design that
       Claude and Codex review several times, each
       without the other's answer, until no real point is left; the person settles it. If
       the types and their lines can stay, the judges' calibration stays. Examples are made
       up, never taken from a task. The finding suite checks it. An explicit read of a page
       whose snippet lacks the facts was planned in the same step and dropped for the MVP:
       what it and a deeper search would need is left to the model and the search's limits.
       Code gives every railway the type railway and an unknown status, since no page that
       the agent can search shows reliably whether trains run; the labels that the MVP agent
       cannot pass are left out, as the eval architecture says. An answer without the Finding
       tool, seen at the selected effort too, makes the object unidentified instead of
       stopping the whole run. Then one full run of E1–E5 measures 8 to 10 against the full
       run of 7. Trace each remaining fail to the first
       failing step: an effect inherited from a wrong type is a classification failure, not a
       separate report fix. The other unselected
       candidates in the [quality audit](evals/2026-10-19-agent-quality-audit.md) are weighed
       only against the failures that this run still shows; they are not scheduled work.
       After the run, the labels whose fails it traced to
       a search that does not reliably reach the page, or to pages that do not settle the
       label, are left out too; and, as row 3 of the audit proposes, a finding that the
       grounding check rejects, or an answer without the Finding tool, gets one more try with
       the reason before the object is unidentified.
    11. Dropped: a Docker image for the CLI. Anyone who runs the CLI needs their own keys,
       with which `uv run` is no harder than a container; Docker comes with the deployment,
       after the MVP.
    12. ✅ The [MVP eval results](evals/2026-10-21-mvp-eval-results.md): each suite's scores
       before and after the fixes of 8 to 10, its failures, the wrong claims apart from the
       objects left unidentified, the known
       limitations above, the labels left out because of the search limits that the
       [search-depth spike](../spikes/search-depth/findings-2026-10-16.md) found, the
       [labels left out of the MVP](eval-architecture.md#labels-left-out-of-the-mvp), and the
       cost of the one-page rule in the end-to-end scores. The
       README says what the agent does, how to run the CLI and the evals, and links the results.

The MVP ends the eval work. Other tasks designed in the eval architecture are available if an
observed failure needs them; they are not a planned phase after the MVP.

## After the MVP: the demo

A small public demo that a reviewer can try without signing up: a clear, pleasant interface
around the existing agent, using Aegra and Agent Chat UI. Keep the implementation simple.

1. ✅ **A held-out check, before any change of the report.** The fixes of steps 8 to 10 were made
   on E1–E5, so their results do not show how the agent does at addresses it was not tuned on.
   Two new Berlin addresses, E6 and E7, cover a railway, a plant against production and a
   housing or mixed plan. The check measures the whole agent at new addresses; it does not
   require a rejected finding to trigger a retry, which existing code tests cover. Their labels
   follow the rules of the eval architecture; one model
   drafts them, another checks them, and the person settles where they disagree. One end-to-end
   run at k=3, with nothing tuned after it; its results are added to the
   [MVP eval results](evals/2026-10-21-mvp-eval-results.md) as a table of their own. Done on
   2026-10-22: every scored label correct, E7 run once more after a map outage.
2. ✅ **The report in Markdown, in sections,** such as the identified objects, the objects that
   could not be identified and the journeys, with the sources and licences at the end, and a
   line from code that a language model wrote the report and its facts should be checked against
   the sources. The CLI stays a technical mode and prints the report as it does now.
3. ✅ **Sources as named links, not numbers:** a page by its site's name, a map object by its
   OpenStreetMap page, a plan by its document where the B-Plan WFS links one.
4. ✅ **Answers in the user's language:** the agent always writes in the language the user
   writes in, the questions and the report alike. A model call names the language from the
   user's messages, the later ones first, and the report model writes in it. A model call translates the texts that code adds, with placeholders that code fills in, so that no value of the run passes
   through the translation. The eval tasks stay in English, so the judges and their calibration do not
   change.
5. ✅ **The demo architecture, before implementation.** Define the services, private access,
   run flow, static examples, limits and retention in the [demo architecture](demo-architecture.md).
   Align [ADR 4](adr/0004-demo-aegra-and-agent-chat-ui.md) and separate the
   [launch checklist](demo-launch-checklist.md) from the technical design.
6. ✅ **The agent as a service on Aegra.** Wrap the existing graph with PostgreSQL checkpoints
   and Redis recovery. Use LangChain messages, interrupt/resume and an explicit final-report
   marker; preserve the CLI, evals and old saved runs. Update the agent architecture with
   the message changes. The scripted dialogue runner and the judge settings moved into
   `evals/`, with their own example environment file.

   Cookie ownership, atomic admission limits, one current conversation per identity, and
   cancellation and deletion with automatic expiry cleanup; admission counters stay after a
   chat is deleted. Reports got explicit Markdown licence links and escaped user text. One
   run executes at a time across all visitors, with Aegra's own worker settings; a question
   to the user frees the slot. The
   [implementation checks](demo-architecture.md#implementation-checks) cover restart and
   resume, quotas, recovery, deletion races and that no source text reaches the browser.
   They run in a disposable Compose project through the
   [integration runner](../demo/testing.md), locally and in CI.

   `demo/compose.yaml` runs the private backend, persistent PostgreSQL and memory-only Redis.
   The backend image installs the agent as a package, runs as a non-root user and holds no
   tests, evals or deployment input. Aegra's migrations and `demo/db/schema.sql` are applied
   separately before the server starts.
7. ✅ **The web interface** in `demo/`, based on Agent Chat UI. Show the private conversation,
   report, progress and fixed service-failure notices, plus reviewed recorded examples.
   The Next.js proxy constructs allowed requests and filters all browser responses.
   Disable unused history, branching, editing and regeneration.
   Show remaining submissions, message limits, clear refusal reasons and the author contact.
   Keep examples available when live input is unavailable.

   - ✅ A small buildable chat layout in `demo/frontend/`, with live input disabled.
   - ✅ Proxy reads with signed-cookie checks and filtered JSON responses.
   - ✅ Filtered event streams and cursor-based reconnection to existing runs.
   - ✅ Admission, cookie issuance, deletion and origin/CSRF checks for mutations.
   - ✅ Restore the private conversation, report, run status and remaining submissions.
   - ✅ Live progress and reconnection without resubmitting a run.
   - ✅ Start notice, configured limits, submissions and manual retries in the interface.
   - ✅ New-chat and deletion controls with confirmation and preserved usage counters.
   - ✅ Five recorded examples with research dates, viewable without a private session.
   - ✅ Service terms, Privacy notice and Impressum pages, linked from the footer and start notice.
8. ✅ **Deployment on one VPS.** Docker Compose runs Caddy, Next.js, Aegra, PostgreSQL and
   Redis, with only Caddy public. PostgreSQL persists; Redis has no disk persistence. Secrets
   are passed at runtime. The [launch checklist](demo-launch-checklist.md) covers operator
   details, notices, provider terms, HTTPS, retention and cleanup; live input was turned on
   only after it and a live trial.

   - ✅ The Web UI image, Caddy as the HTTPS reverse proxy, host setup and release scripts,
     checked locally.
     Images are built locally and copied to the server, which has 1 GB of memory.
   - ✅ The server prepared; the recorded examples served over HTTPS at
     <https://outofframe.hooraytalk.com>, with live input off.
   - ✅ Transfer safeguards in the Privacy notice: Anthropic's DPA with the EU Standard
     Contractual Clauses; Tavily receives no visitor identifiers. A
     [legitimate interest record](demo-legitimate-interest.md) for quotas and security logs.
   - ✅ Launch checklist and live trial on 2026-10-25: a report with working links and
     Delete chat, which removed the thread, runs, checkpoints and Redis data and kept only
     the quota counters. Live input is on. The 30-day expiry was not observed on the
     server; the integration checks cover it.
9. ✅ **The README in its final form:** a CI badge and a link to the demo; the design choices,
   one line each; what is out of scope; the legal frame and a link to the data sources and
   their rights in [sources.md](sources.md).
   - ✅ Two ADRs that record decisions made on 2026-09-21:
     [an agent for the investigation, a workflow for the rest](adr/0002-why-an-agent.md) and
     [live sources instead of an index of our own](adr/0003-live-sources.md).
   - ✅ No MCP and no baseline: one line each, without an ADR.
   - ✅ The private live chat and the five recorded examples.
10. **Bound demo connections and request traffic.**
    - ✅ At most 10 progress streams across visitors and 2 per identity; at most 20 API
      requests per second, with a burst of 40. Refusals change no runs or quotas.
    - Validate these limits under load on the VPS before raising them.
11. ✅ **At most two commute destinations by default.** For a longer list, code asks the user
    which to keep, before any source calls.
