# Problem Set 4 Intelligence and Influence

**MIT 1.125**  
**Format:** Individual assignment  
**Duration:** One week

Read the [architecture specification](ARCHITECTURE.md) for required commands, interfaces, and data formats. Complete [SUBMISSION.md](SUBMISSION.md) with your project details, evidence, and publication links.

## Objective

Build a repeatable pipeline that collects recent information, directs AI to make editorial decisions, and produces a publication for a specific audience. Use it to publish a connected series of three Substack articles, each accompanied by a YouTube video.

Use AI for editorial selection, synthesis, and generation of article drafts and video scripts. Your responsibility is to design the process, direct its judgment, and verify its results.

Choose a field in which you would like to develop a credible voice. Your contribution should help an audience understand developments, assess competing claims, and form better questions. Your system must produce original synthesis grounded in traceable evidence.

The central engineering task is to make this process repeatable. You must understand the architecture, explain the AI's editorial choices, and demonstrate how the system responds to new information.

## Topic and Audience

Choose **one topic and one audience** for the entire series. Define a question your audience would benefit from revisiting regularly.

For example, you might investigate AI documentation tools for physicians running small practices, construction robotics for project managers, or AI music tools for independent musicians. Narrow the topic enough to support specific conclusions within one week.

Write a brief stating:

- Who the audience is and what they already understand.
- What question, decision, or professional interest the publication serves.
- What the publication includes and excludes.
- Why a reader would return for the next edition.

Give the publication a name and a consistent editorial voice.

## Source Collection and Freshness

Your pipeline must collect and process all three input types:

| Input | Required capability |
| --- | --- |
| RSS feeds | Discover entries, retrieve substantive source content, and identify previously processed items. |
| YouTube video | Retrieve video or audio content, obtain or generate a transcript, and preserve timestamps linking evidence to the video. |
| Podcast audio | Retrieve podcast audio, obtain or generate a transcript, and preserve timestamps linking evidence to the episode. |

Audio and video must contribute distinct original material. A podcast episode and its YouTube upload count as one item. An RSS entry that points to that episode is a discovery route, not an additional item.

Collect at least **12 distinct substantive items from six independent sources**, including at least two items of each input type. For RSS, the two items must lead to substantive written material. A source may be a publisher, organization, channel, or podcast. Reposts and syndicated copies do not establish independence. These are minimum coverage requirements; collecting more material alone does not improve your grade.

Include different perspectives, such as research, commercial announcements, and practitioner experience. Explain whose perspectives are missing. Web scraping, computer use, comments, and tools such as the last30days skill may supplement the required inputs.

**All substantive source material must have been published within the preceding 30 days.** Each publication must state an as-of date equal to the actual execution date of the pipeline run that supplied its evidence. Apply the 30-day window relative to that date. Complete the submitted runs during the assignment week.

Record publication dates separately from collection dates. Exclude undated material from the evidence supporting your publications. An old recording uploaded again or an unchanged article with a refreshed date does not become a new development. Identify when a recent source discusses an older event, and explain what is newly reported or learned.

## Editorial Judgment and Original Synthesis

Create an explicit editorial policy that the pipeline supplies to the AI during selection and synthesis. The policy must address audience relevance, freshness, source credibility, novelty, and diversity of perspectives. Explain how the system handles uncertainty, conflicting evidence, commercial incentives, and unsupported claims.

Credibility assessments must consider the evidence for a particular claim. Institutional reputation, popularity, and model confidence are insufficient by themselves. Several sources repeating the same announcement count as one underlying claim, not independent corroboration.

Save the actual prompts or instructions used, along with structured editorial decisions. For each candidate item, record whether the system accepted, rejected, or deferred it and why. Record which article uses each selected item.

Develop three connected pieces with distinct editorial purposes:

| Piece | Editorial question |
| --- | --- |
| 1 | What changed, and which developments matter most to this audience? |
| 2 | Which claims withstand scrutiny, and where are the evidence or interpretations in tension? |
| 3 | What do these developments imply for the audience, and what should they watch next? |

Each piece must:

- Advance a distinct central argument supported by at least three independent sources.
- Develop at least one insight by connecting evidence from multiple sources. Explain the reasoning and what your analysis adds beyond the individual sources.
- Distinguish reported facts, source claims, your interpretation, and remaining uncertainty.
- Address a meaningful limitation or counterargument. Do not manufacture disagreement when the evidence does not support it.
- Link substantive claims to evidence, including timestamps for audio or video passages.

All three required input types must contribute evidence to the series. You may reuse evidence across pieces when it serves a different argument. Each piece must make an additional intellectual contribution.

An original contribution might reveal a mismatch between a product announcement and practitioner experience, explain why two apparently conflicting results differ, or identify a shared constraint across several developments. A list of summaries, a compilation of quotations, or three rewrites of the same argument does not satisfy this requirement.

Review a sample of at least **three accepted and three rejected or deferred items**. Compare the AI's reasons with your own judgment. Revise the editorial policy at least once, rerun the affected stage, and document how the choices or synthesis changed. Preserve any human corrections to factual claims and explain why they were necessary.

## System Architecture

Use the supplied **intelligence-pipeline-starter** repository structure. It contains **16 empty Bash files** for you to implement. The [architecture specification](ARCHITECTURE.md) defines the required commands, data formats, artifacts, and failure behavior. These contracts are part of the assignment.

```text
intelligence-pipeline-starter/
├── README.md
├── ARCHITECTURE.md
├── SUBMISSION.md
├── run.sh
├── workflows/
│   ├── collect_sources.sh
│   └── create_series.sh
├── collectors/
│   ├── fetch_feeds.sh
│   ├── fetch_youtube.sh
│   └── fetch_podcasts.sh
├── processing/
│   ├── extract_content.sh
│   └── filter_items.sh
├── data/
│   └── store.sh
├── editorial/
│   ├── select_items.sh
│   └── create_briefs.sh
├── content/
│   ├── write_articles.sh
│   └── write_video_scripts.sh
├── review/
│   └── check_content.sh
├── publishing/
│   └── prepare_package.sh
├── reporting/
│   └── summarize_run.sh
├── config/
│   ├── project.json
│   ├── sources.json
│   └── editorial_policy.md
├── prompts/
│   ├── select_items.md
│   ├── create_briefs.md
│   ├── write_articles.md
│   └── write_video_scripts.md
└── examples/
```

Each Bash file has one required responsibility:

| File | Responsibility |
| --- | --- |
| `run.sh` | Establish the run, call the workflows, and report its outcome. |
| `workflows/collect_sources.sh` | Coordinate collection, extraction, storage, and freshness filtering. |
| `workflows/create_series.sh` | Coordinate editorial decisions, briefs, article and video-script generation, and content checks. |
| `collectors/fetch_feeds.sh` | Discover written items from configured RSS feeds and emit source metadata. |
| `collectors/fetch_youtube.sh` | Discover configured YouTube material and emit source metadata. |
| `collectors/fetch_podcasts.sh` | Discover podcast episodes and their audio locations. |
| `processing/extract_content.sh` | Retrieve substantive text or media, prepare timestamped transcripts, and produce normalized evidence records. |
| `processing/filter_items.sh` | Apply the 30-day window and record eligible items and exclusion reasons. |
| `data/store.sh` | Own persistent evidence storage, stable identities, version history, and duplicate handling. |
| `editorial/select_items.sh` | Apply the editorial policy through AI and record selections, rejections, and deferrals. |
| `editorial/create_briefs.sh` | Develop three distinct arguments with explicit claims and supporting evidence. |
| `content/write_articles.sh` | Generate three article drafts from the briefs. |
| `content/write_video_scripts.sh` | Generate three audience-facing scripts from the same briefs. |
| `review/check_content.sh` | Check drafts, references, freshness, and consistency; report issues for human review. |
| `publishing/prepare_package.sh` | Assemble reviewed articles, video scripts, and references for production and publication. |
| `reporting/summarize_run.sh` | Report source coverage, changes, stage outcomes, costs, and remaining manual work. |

**Keep every required filename and responsibility.** You may add focused helper files, providers, and collectors. Scripts may call Python, JavaScript, model APIs, command-line agents, and existing packages. Preserve the component boundaries: a shared implementation that performs the whole pipeline behind superficial wrappers does not satisfy the architecture requirement.

Keep `run.sh` and the two workflows focused on coordination. Each substantive component must be independently runnable using the documented interface. Use JSON Lines for records passed between components, with the required fields and meanings in `ARCHITECTURE.md`. Save intermediate artifacts so graders can inspect or replay a stage.

**Only `data/store.sh` may directly read or write the persistent evidence index or database.** Other components use its commands. You may choose SQLite or a documented file format behind this interface. Retained source files, transcripts, run artifacts, and configuration are separate from this index and may be accessed by their responsible components.

Keep topic settings, source lists, editorial policy, and model prompts in their prescribed files. Record the models and tools used, execution time, and approximate cost of each run. Reuse unchanged stored material where possible.

The automated pipeline must reach article drafts, video scripts, evidence references, and content checks. Google Vids or HeyGen production and platform publishing may involve manual steps. `prepare_package.sh` provides that handoff after human editorial review; it is not required to publish through platform APIs. Document the remaining manual actions accurately.

## Published Series

Publish **three Substack articles and three accompanying YouTube videos** for your chosen audience.

- Each article should be approximately **600–900 words**, excluding references.
- Each accompanying video should be approximately **3–5 minutes**, presenting the article's central argument in a form suited to viewing and listening.
- Use **Google Vids or HeyGen** to produce each audience-facing video. An avatar, including a custom avatar, is optional.
- Generate the article and its video script from the same reviewed evidence and editorial brief. Keep their factual claims consistent.
- Link each article to its video. Include the article and source references in the video's description, and make evidence references understandable to viewers.

Publish the Substack articles with shareable access and without a paid subscription requirement. YouTube videos may be public or unlisted. Verify that course staff can open every submitted link.

You are responsible for reviewing the material before publication. Attribute source material and identify AI-generated presentation where used. Assessing credibility also requires recognizing where the available evidence does not justify a confident conclusion.

## Repeatability Demonstration

Complete at least **two pipeline runs on different days**. Preserve their inputs, outputs, and logs so the differences are inspectable.

Demonstrate that the system:

- Identifies newly discovered or changed material and explains any resulting editorial changes.
- Avoids duplicate records and unnecessary processing when the same inputs are replayed.
- Applies the 30-day window and records why material is excluded.
- Reports a failed collection attempt and continues with an explicit account of incomplete coverage, or resumes successfully after the failure is resolved.

If no meaningful new material appears between runs, report that result. Demonstrate the update behavior using a clearly labeled replay that introduces a previously withheld, eligible item. Label deliberately simulated failures as well.

Submit three article/video pairs in total. Later runs may revise existing drafts or supply later pieces in the series; they do not require another complete published series.

## Technical Demonstration Video

Record a separate **4–6 minute narrated demonstration** of the system you built. This video is for evaluating the system's capabilities and your architectural understanding.

Show the architecture and entry point, trace one source through an editorial decision into a published claim, and demonstrate the second run. Include evidence of duplicate handling or failure recovery. Explain one human correction or policy revision and one significant architectural tradeoff.

Make the relevant files, records, and outputs readable. The technical demonstration is separate from the three audience-facing videos.

## Submission

Submit a GitHub repository based on the supplied starter, with all 16 required scripts implemented. Include the saved editorial policy and prompts, dependency and setup instructions, and enough sample evidence and intermediate artifacts from both runs to inspect the complete workflow. The starter's fictional examples demonstrate formats and do not count as collected evidence. Keep credentials out of the repository. Document how to retrieve any media that you retain locally but cannot include.

Complete the repository's [SUBMISSION.md](SUBMISSION.md) as the entry point for your work. Preserve the course instructions in `README.md` and `ARCHITECTURE.md`. Include:

1. Your topic, audience, publication purpose, and links to all three Substack articles and YouTube videos.
2. A link to the separate technical demonstration video.
3. An architecture diagram and the command needed to run the pipeline.
4. Setup requirements, configuration instructions, and a description of manual handoffs.
5. Locations of the evidence store, editorial decisions, review sample, policy revision, and records from both runs.
6. A short reflection on one insight the system produced, one editorial failure or limitation, and the next improvement you would make.

Be prepared to explain any component and trace a published claim back to its original evidence.

## Evaluation

| Criterion | Weight | Evidence of strong work |
| --- | --- | --- |
| Architecture and repeatability | 40% | All required components implement their assigned responsibilities and interfaces; intermediate artifacts, persistent state, updates, and failure behavior are demonstrated. |
| Evidence quality and freshness | 25% | Meaningful use of all required inputs, independent sources, verified dates, traceable claims, and careful treatment of credibility and uncertainty. |
| Editorial judgment and original synthesis | 25% | A working editorial policy, defensible selections and rejections, an examined policy revision, and three distinct arguments that connect evidence. |
| Communication and publication | 10% | A coherent, accessible series for the chosen audience, usable links, and a clear technical demonstration. |

Production polish contributes within the communication criterion. Audience size, likes, and follower counts are not grading criteria.

## Suggested Schedule

Use the first two days to establish the topic, audience, source collection, and evidence store. Complete an initial end-to-end run by day three. Use days four and five to examine editorial decisions, revise the policy, and develop the series. Complete the second run and publication by day six. Reserve the final day for verification, documentation, and the technical demonstration.

Choose a subject you would want to keep following after the assignment. The result should be a system you can run again and a publication whose reasoning readers can inspect.
