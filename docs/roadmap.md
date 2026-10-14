# Roadmap

The intended order to the MVP. Each step names its result and checks. Detail the next step
before starting it; leave later implementation details open. Change the order when a run
reveals a reason, and keep the next step clear here.

For each new behaviour, prepare its eval cases and success criteria before implementing it.
For code, write a failing test, implement the behaviour and refactor. Extend the eval harness
only as needed. Each step ends with the tests and eval tasks that can run by then, with
failures recorded. Review the first findings and reports by hand against the judge rubrics;
these grades go into the judges' calibration sets. Quote LLM judge scores only after
calibration.

1. ✅ **Repository setup.**
2. ✅ **Research scope.** Each checked category with its radius and its source. Kept as
   data.
3. ✅ **Spike.** How many objects of each category does Overpass return, and how many have no
   name? This sets the investigation cap per category. Exploratory scripts live in `spikes/`, one
   folder per question, each with a dated note of its findings:
   [overpass-counts](../spikes/overpass-counts/findings-2026-09-25.md). The findings may change
   the research scope. The scripts stay outside the checks and are never extended.
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
8. **Development plans.** Add the B-Plan WFS branch and feed its objects into the existing
   investigation. Check E4 with no commute destinations, plus code tests for filtering,
   distances, limits and source failure. The report must distinguish a plan's legal status
   from evidence about whether building has started, including when that status is unknown.
9. **Commute.** Add Transitous journeys there and back. Test duration calculation, no route
   and unavailable outcomes; run the end-to-end cases with one and two destinations. The
   report must give the right destination, direction and duration, or the missing-route reason.
   From step 7: the input conversation asks where the user travels and when, a destination
   may be outside Berlin, and I1 and I3 check it.
10. **Judge calibration and MVP results.** Calibrate the three MVP judges against human grades
    of the first real outputs and deliberately faulty examples. Complete and run every
    [MVP task](eval-architecture.md#mvp), several trials each; check that the labels cover
    every category. Publish results with failures and limitations. Add one Docker
    image for the CLI; the keys are passed at run time, never built into the image.
    From the first hand grades: the support and interpretation rubrics count an effect on a
    resident, such as traffic, as backed only when the type's line or a source gives it, and
    the person checks the grades of evals/calibration/ against the changed rubrics.
    From step 6: the labelling script, F2 and F6; the support rubric checks the type of a
    triage finding only against its label, as the eval architecture says, since triage may use
    what the model knows; the interpretation rubric lets an object whose type alone shows no
    effect have one short sentence, as the report prompt asks since step 6.4. A known
    limitation to publish: a site that several businesses share gets the type of the business
    that the investigation finds. At Klärwerkstraße 1 and 1a, runs found a cleaning business
    and a Jobcenter project, both commercial, and missed a metalwork shop with production halls
    there. From the live runs of step 6.5: a finding can cite a page that does not back its type
    or status, such as an Impressum with an address only, or cite the map though a page it read
    settles the status, so that a running S-Bahn line reads as "unknown whether in use".

The MVP is the intended stopping point. Other tasks designed in the eval architecture are
available if an observed failure needs them; they are not a planned phase after the MVP.
