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
5. **First working slice: investigate one object.** As a CLI: a precise address → one unclear
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
   5. The CLI path: Nominatim, Overpass, the object choice and the report with sources. Check
      the whole path with replayed sources and a stubbed model.
   6. The rubrics of the three MVP judges, written with the first report. Run the judges
      uncalibrated; their scores are not quoted until they pass calibration in step 10.

   The result must demonstrate a supported finding and an honest unidentified outcome when
   evidence is missing; inspect the first report by hand.
6. **Several objects and triage.** Extend the path to map categories, grouping, nearest-N limits
   (five per category), code routing, triage and parallel investigations. Add the
   [labelling script](eval-architecture.md#ground-truth-labels), which uses the grouping code.
   Check T1–T2, F2, F6 and R2–R4, plus
   code tests for routing (T3), grouping, distances, caps and failures. The report must preserve
   clear findings, show unidentified and not investigated objects, and distinguish an empty
   result from a failure.
7. **Input conversation.** Add extraction, address disambiguation, questions and LangGraph
   pauses. Check I1–I3 and code tests for applying changes and resuming the run. The user can
   resolve an ambiguous address and supply missing times; complete input starts research
   without a question. Journey calculation comes in step 9.
8. **Development plans.** Add the B-Plan WFS branch and feed its objects into the existing
   investigation. Check E4 with no commute destinations, plus code tests for filtering,
   distances, limits and source failure. The report must distinguish a plan's legal status
   from evidence about whether building has started, including when that status is unknown.
9. **Commute.** Add Transitous journeys there and back. Test duration calculation, no route
   and unavailable outcomes; run the end-to-end cases with one and two destinations. The
   report must give the right destination, direction and duration, or the missing-route reason.
10. **Judge calibration and MVP results.** Calibrate the three MVP judges against human grades
    of the first real outputs and deliberately faulty examples. Complete and run every
    [MVP task](eval-architecture.md#mvp), several trials each; check that the labels cover
    every category. Publish results with failures and limitations. Add one Docker
    image for the CLI; the keys are passed at run time, never built into the image.

The MVP is the intended stopping point. Other tasks designed in the eval architecture are
available if an observed failure needs them; they are not a planned phase after the MVP.
