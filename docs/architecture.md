# Architecture

How one run works, who decides at each step, and where text from the web enters.

```mermaid
flowchart TD
    subgraph INTAKE["Phase 1: Intake, a conversation until the input is complete"]
        direction LR
        START((" ")):::start
        U(["User<br/><i>an LLM simulator in evals</i>"]):::human
        M["Read the message<br/>pick out addresses and answers"]:::model
        G["Geocode new addresses"]:::code
        NOM[["Nominatim<br/>geocoding API"]]:::ext
        PR[("Property location<br/>Commute destinations")]:::data
        C{"Anything missing<br/>or unclear?"}:::code
        A["Ask for it"]:::model
        DONE(["Input complete"]):::milestone
        START --> U
        U -->|"any message"| M
        M --> G --> PR --> C
        G --- NOM
        C -->|"yes"| A
        A -->|"question"| U
        C -->|"no"| DONE
    end

    subgraph RESEARCH["Phase 2: Research, branches in parallel"]
        direction TB
        J(["Research starts"]):::milestone
        subgraph SUR["Branch: surroundings"]
            OV["Map objects<br/>nearest N per checklist class"]:::code
            OVP[["Overpass API<br/>OpenStreetMap data"]]:::ext
            T["Triage<br/>which objects are unclear<br/>capped in number"]:::model
        end
        subgraph PLN["Branch: planned development"]
            PL["B-Plans in the radius<br/>and their status"]:::code
            WFS[["Berlin B-Plan WFS<br/>city planning data"]]:::ext
            PS{"Status clear?"}:::code
        end
        subgraph COM["Branch: commute"]
            TR["Journeys there and back<br/>per destination, averaged"]:::code
            TRA[["Transitous<br/>journey planner API"]]:::ext
        end
        subgraph INV["Investigate one object: shared by the branches, its own context"]
            S["Search the web<br/>the model writes the query"]:::model
            TAV[["Tavily<br/>web search API"]]:::ext
            D{"Enough?<br/>or cap reached"}:::model
            F["Finding<br/>class, status, why it matters<br/>with its evidence and key facts<br/>or unidentified"]:::model
        end
        FS[("Findings, plans, journeys<br/>each with its evidence")]:::data
        JN(["Research complete"]):::milestone
        J --> OV
        J --> PL
        J -->|"if any destinations"| TR
        OV --> T
        OV --- OVP
        T -->|"per unclear object"| S
        PL --> PS
        PL --- WFS
        PS -->|"unclear"| S
        S --> D
        S --- TAV
        D -->|"search again"| S
        D -->|"stop"| F
        T -->|"clear from the data"| FS
        PS -->|"clear"| FS
        F -->|"finding only, not the transcript"| FS
        TR --> FS
        FS --> JN
        TR ~~~ PS
        TR --- TRA
    end

    subgraph REPORT["Phase 3: Report"]
        direction TB
        RS(["Report starts"]):::milestone
        W["Write the report<br/>from the state, with its own prompt<br/>unidentified objects in the footer"]:::model
        OUT(["Report to the user"]):::human
        STOP(("●")):::stop
        RS --> W --> OUT --> STOP
    end

    INTAKE --> RESEARCH
    RESEARCH --> REPORT

    subgraph KEY["Who does what"]
        direction LR
        k1(["User"]):::human
        k2["Model decides<br/><i>Claude, Anthropic API</i>"]:::model
        k3["Code decides"]:::code
        k5[["External API"]]:::ext
        k4[("State and data")]:::data
        k1 ~~~ k2 ~~~ k3 ~~~ k5 ~~~ k4
    end
    REPORT ~~~ KEY

    classDef human fill:#fcd34d,stroke:#92400e,color:#111827
    classDef model fill:#c4b5fd,stroke:#5b21b6,stroke-width:2px,color:#111827
    classDef code fill:#ffffff,stroke:#475569,stroke-width:1.5px,color:#111827
    classDef data fill:#e5e7eb,stroke:#6b7280,color:#111827
    classDef ext fill:#bbf7d0,stroke:#15803d,stroke-width:1.5px,color:#111827
    classDef milestone fill:#f1f5f9,stroke:#475569,color:#111827
    classDef start fill:#1f2937,stroke:#1f2937,color:#1f2937
    classDef stop fill:#ffffff,stroke:#1f2937,stroke-width:2px,color:#1f2937
    style INTAKE fill:#f8fafc,stroke:#64748b
    style RESEARCH fill:#f8fafc,stroke:#64748b
    style REPORT fill:#f8fafc,stroke:#64748b
    style SUR fill:#e2e8f0,stroke:#94a3b8
    style PLN fill:#e2e8f0,stroke:#94a3b8
    style COM fill:#e2e8f0,stroke:#94a3b8
    style INV fill:#e2e8f0,stroke:#94a3b8,stroke-dasharray:5 3
    style KEY fill:#f8fafc,stroke:#94a3b8
```

## One run

A run has three phases and one state. Only the state passes from one phase to the next.
Nothing is kept for the next run.

1. **Intake** is one loop for any first message: a greeting, an address alone or a full
   request. The model finds the addresses and answers in the message. Code geocodes each new
   address, saves it in the state and checks what is still missing or unclear. The model then
   asks the user for it. If an address is ambiguous or outside Berlin, the user gets a
   question. After intake, the property is stored as one point (latitude and longitude). The
   code that calls each source converts this point to the format that source needs; the
   Berlin WFS, for example, uses a different coordinate system. Coordinates are converted
   only in code.
2. **Research** runs in parallel branches after the input is complete.
   - *Surroundings:* one Overpass query returns the nearest objects of each checklist class,
     up to a fixed number per class, each class within its own radius. The model marks each
     object as clear or unclear. Clear objects go into the state as they are. Unclear objects
     are investigated, nearest first, up to a fixed number per class; the rest are listed in
     the report as not investigated.
   - *Planned development:* one query to the Berlin B-Plan WFS. Plans with an unclear status
     are investigated in the same way as unclear map objects.
   - *Commute:* only if the user named places they travel to regularly. Each place has its
     own times, so two people with different schedules give two entries. For each place, code
     asks Transitous for two journeys on a normal weekday: there, at the time the user usually
     leaves, and back, at the time they usually return. Each journey is the average of the
     next three connections.
3. **Report.** The model writes the report from the state, with its own prompt. Objects that
   could not be identified are listed at the end of the report. They are not removed.

## Who decides

The model decides:

- in intake: what the message contains (addresses, places, times) and how to ask for what is
  missing;
- in triage: which map objects are unclear;
- in an investigation: what to search for, whether to search again, and what the finding is;
- in the report: what to highlight and how to say it.

Code decides what runs next. It reads the state and follows fixed rules: it asks the user
when something is missing, starts one investigation per unclear object, and plans journeys
for each place the user named. The model changes the path only through what it writes into
the state. There is no LLM router.

The one exception is the investigation loop: there the model itself decides to search again
or stop, with at most a fixed number of web searches per object.

Other rules:

- **The model writes no queries for the map, plan or transit sources.** These sources run
  fixed queries with fixed radii. The model's only tool is web search.
- **Each investigation runs in its own context.** Only the finding and its evidence IDs return
  to the state, not the full transcript.
- **The agent has no clock.** Each run gets the date as input. Status comes only from dated
  sources, never from the model's memory.

## Grounding

Every finding must be grounded in stored sources. Code gives every source response and search
result an ID and stores it. A finding cites the IDs it uses and its key facts (a name, a date,
a status), written exactly as in the source. When a finding is written, code checks that each
ID exists and that each fact appears in the stored text. If the check fails, the finding is
rejected. The agent then searches more, within the object's search limit, or marks the object
as unidentified. Code fills in the references in the report from the evidence, so the model
cannot invent one.

## Prompt injection

Search results come from other websites and may contain prompt injection: text written to
give the model instructions. This text reaches only the investigation that ran the search.
Code limits what it can do: the model's only tool is web search, the number of searches is
capped, and every fact in a finding must appear in a stored source, so it can be traced to its
page. Injected text can still mislead the model, for example with false facts on a page. Evals
measure how often this happens.

## Failures

If a source fails, code tries again. If it still fails, the report marks that branch, and the
other branches continue. "The source failed" and "nothing was found" are different states in
the report.
