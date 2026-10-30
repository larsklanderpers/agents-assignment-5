# Assignment 5: Reflection

Lars Klander | UCLA Extension — Agentic AI | 30 October 2026

This reflection is based on the implementation, automated tests, live evaluations and browser walkthrough completed with Codex assistance. It distinguishes the supplied starter components from the work added for this assignment.

## Part 1: LangGraph Workflow

### 1. Designing the eight-node workflow

The standard workflow separates validation, risk assessment, human review, budget checking and final processing into distinct nodes. Its order follows the assignment’s escalation policy.

- Low-risk requests go to budget validation and can be approved automatically when within budget.

- Medium-risk requests require manager approval before the budget check.

- High-risk requests require manager and finance approval.

- Critical requests add executive sign-off.

The addition of the later bonus route adds to the logic the processing of two high-risk reviews in parallel, while preserving the standard sequential route as the default. A rejection prevents approval; the parallel route records both review decisions before closing.

The budget-escalation paths required particular care and iteration, in part because while they are reasonably intuitive to anyone who has ever worked in a large company, they are a but non-intuitive to an agent process:

- a low-risk request above its department budget goes to the manager;

- an over-budget medium-risk request goes to finance after manager approval and budget validation;

- Finally, high and critical requests skip the automatic budget check, as specified in the starter.

Keeping these paths explicit makes the approval requirements easier to inspect and test, which helped a lot when I got to the observability portion of the assignment.

### 2. Implementing interrupt and resume

The useful idea behind interrupt() is that the graph can pause at a review node, expose the information a reviewer needs, and continue when a decision is supplied ( i suppose it emphasizes my old-school-ness to think of this like a debugging run with an breakpoint in it). The demanding part was preserving the contract between the graph and the frontend. The starter used JSON-string responses; the completed interface also supports standard responses addressed to specific interrupt IDs, which added a layer that the JSON-string model couldn’t really handle alone. The review code accepts a decision object or a legacy JSON string and requires “approved” to be an actual boolean; a string such as "true" or a “1” doesn’t qualify as approval, and therefore must be treated as a rejection. Parallel reviews made correct response-to-interrupt matching especially important, and that required a number of further iterations to ensure that there weren’t implicit sequencing dependencies in the logic..

Persistence also matters, once we add interrupt support, so the system knows how to properly resume during an evaluation run. The server uses AsyncSqliteSaver because its agent endpoint calls the asynchronous graph API. Tests verified both asynchronous resume and reopening a saved SQLite checkpoint. Each new request also resets earlier risk, budget and decision fields because the frontend reuses a conversation thread. Without that reset, an earlier request could contaminate the next one; the down side is that there is no ongoing persistence of that thread at this point. A logical improvement and expansion would be to hold onto request threads so that the reasoning and decision-making could be reviewed again later, even after dozens or hundreds of iterations of the actual approval flow itself have been completed.

### 3. Why conditional routing matters

The six standard routing functions turn state into the next workflow stage. They consider validation, risk, budget status and reviewer decisions rather than relying on a single linear sequence. Standard routes can stop on rejection and avoid unnecessary review on simpler requests; however, the parallel bonus adds an explicit fork and join structure to support the parallelism. The model classifies risk, while code implements escalation. A production version should also enforce deterministic minimum review requirements so an incorrect model classification cannot reduce the required oversight. I know I always go on about Jev, but a classification/decision model would be useful in multiple places here, and were it now so clearly outside the scope of the project, I definitely would have added one.

## Part 2: Safety Guardrails

### 1. Input protection and its limits

Input validation rejects zero or negative amounts, non-finite values, amounts above the overall ceiling, invalid departments and oversized text fields. It also blocks known SQL injection, script and code-execution patterns in the title, description and justification. Case normalization, HTML-entity decoding and whitespace normalization help catch some simple variations.There are probably a hundred other combinations I could have pursued, but since I don’t really have a testing resource and tools like playwright are not permitted, I stuck with what I could easily come up with.

These checks are useful guardrails, not a complete security boundary. A pattern list can miss unfamiliar or obfuscated attacks and may reject harmless text. The risk prompt treats request text as untrusted data, but that instruction alone cannot guarantee resistance to prompt injection. A real financial system would also need authenticated users, reviewer authorization, careful output rendering and server-side enforcement of policy.

### 2. PII masking and usability

Output filtering masks Social Security numbers, card numbers, email addresses and phone numbers using regular expressions. Financial filtering masks account numbers of eight or more digits while retaining the final four, and masks dollar amounts while retaining three numeric digits. The review caught an error in the initial amount implementation: taking the final three characters counted the decimal point as one of them. The corrected version turns $45,678.91 into $\*\*\*8.91 and preserves sentence-ending punctuation. Seven other added regression cases cover decimal amounts, whole-dollar amounts, shorter amounts and repeated filtering.

Masking creates a usability trade-off. Removing too much detail can make review difficult, while retaining too much can reveal sensitive information. Generic numeric patterns can also mask a request identifier as though it were an account number. A stronger design would classify fields by purpose and viewer role, rather than applying the same text rules everywhere.(Again, Jev!) Also, a standard renderer allowing for one-at-a-time field display would probably have utility.

### 3. Why validate inputs and filter outputs

Input validation checks whether a given request is acceptable; it does not guarantee that every later message is safe to display, and so each request needs to be validated accordingly. A model may repeat information from a request, and human review comments may introduce additional personal details. Filtering outgoing summaries and reviewer comments provides a separate layer of protection. The system still needs appropriate access controls around its structured request data and traces; sanitizing chat messages does not make every stored field public-safe.Most of those issues were beyond the scope of the rubric and so were left alone, but if I were taking this to production, would be one of my first items off the rank.

## Part 3: CopilotKit Frontend

### 1. Connecting frontend decisions to the graph

The supplied frontend used useLangGraphInterrupt to render an approval panel when the graph paused. Supporting parallel reviews required moving to the style-free useInterrupt hook, which exposes the full set of pending interrupts. Each response is addressed to its interrupt ID, so a finance decision cannot accidentally resume the manager’s task. The modal now renders outside the chat container, and its review tabs show both open roles, mostly because its the only way I could figure out to do it. In this local UI, both selections are collected before they are sent together; the backend also supports responses submitted independently. This, too, would be a valid front-end improvement before deployment – the finance person and the manager person will presumably be using different computers, so the parallel feed needs to support multiple endpoints.

### 2. Reviewing the user experience

The modal interface began with the supplied starter and was expanded through the walkthrough. Reviewers now see the applicable amount and priority rules, why their stage is required, their responsibilities, and the configured budget comparison even when automatic budget validation is skipped. That comparison is clearly labelled as reference information rather than a live accounting balance or a completed budget check. The request form now has three steps: request details, business case, and review before submission. It asks what is happening, what supports that account, who is affected, and why the proposed response and cost are justified. Urgent requests need a reason for urgency. These details remain requester-reported claims; a request to “restore service” does not establish that a service is down.

An early browser walkthrough used a fictitious urgent $95,000 engineering request, classified as critical. The manager, finance and executive panels appeared in order, and the final response listed all three approvals. Later walkthroughs checked a parallel high-risk approval, a parallel rejection and a standard medium-risk approval. The progress and history panels are now connected to persistent backend activity. They distinguish completed, waiting and skipped stages instead of implying that every request followed the same linear path. This is not only more appropriate for the redesigned flow, its better design across the board for modern systems.

### 3. Integration challenges

The main integration issues were response formats, asynchronous checkpointing and updating shared state safely. Standard sequential reviews return the accumulated decision list. Parallel branches instead write separate manager and finance decision fields, then a join combines them; this avoids competing writes to the same state field. The pinned Python adapter also needed a small compatibility subclass to preserve interrupt settings when cloned and translate addressed responses into LangGraph’s native ID-to-decision map. HTTP integration tests exercised both batched responses and Finance responding first. Tests also checked that a partially reviewed request could resume after reopening its checkpoint. Mostly, the usual battery of different items that need to be addressed when an expansion of capacity is identified in any organization;

## Part 4: LangSmith Tracing and Evaluation

### 1. Partial credit for risk predictions

The risk evaluator uses the ordered levels low, medium, high and critical. An exact match receives 1.0, adjacent levels receive 0.5, and other mismatches receive 0.0. Requests rejected during submission never reach risk assessment, so their risk level is None. Comparing exact matches first lets None versus None score correctly without attempting to look up None in the ordered list. The approval-consistency evaluator separately checks whether the final approved or rejected status matches the reference.

### 2. Why evaluation needs several kinds of evidence

The most important evaluation distinction was between testing the evaluators and testing the agent. The supplied runners score reference outputs against themselves. That is useful for checking scoring logic, but it does not prove the graph produces those outputs. An additional runner therefore executes the real graph, records its node path and decisions, and compares the resulting risk level, status, approval path and review count with the references.

The final local test suite contains 145 passing tests, including 17 bonus-specific checks. Execution tests use an explicit model double for repeatable checks, while separate live runs use GPT-6 Luna. Coverage includes the supplied scenarios, rejection at every review stage, stale-state resets, SQLite recovery, asynchronous resume, malformed decisions, dataset generation, parallel routing, audit persistence and notification deduplication. A further check confirms that assessment is shown as in progress while the model is working, rather than only after its response arrives. These checks establish specific behaviors, not complete production readiness, not even close. I am sure you already know that, just wanted to make sure I state it explicitly for clarity.

### 3. What the results showed

All 12 supplied requests matched their expected outcomes in the live graph evaluation, and the nine deterministic metric averages were 1.00. Human approvals in that runner were simulated, so this measures execution and policy routing under those decisions rather than the quality of real human judgment (something which recent news stories about testers and engineers have emphasized is clearly a problem, even with your most educated workers). Browser walkthroughs separately verified the actual approval controls. Earlier live workflow runs were also confirmed in LangSmith, providing evidence beyond local test output. The later verification runs kept results local rather than uploading new evaluations.

The supplied reference-only three-layer runner reported approximately 0.97 overall, but that is not a score for actual agent execution. A broader live run reported goal accuracy of 1.00 and topic adherence of 0.819. After improving the evidence comparison, the final focused live run scored 0.949 on faithfulness and 1.00 on its nine deterministic metrics. The focused run did not rerun topic adherence or goal accuracy. These results come from different runs and coverage, so they should not be combined into a single overall grade or presented as a direct before-and-after experiment. Model judges also vary between runs. A classification model used together with the LLM might give a more accurate scoring on a repeat-process basis to the third or fourth digit of precision, should we decide to add that after the fact.

## Part 5: Three-Layer Evaluation and Dataset Generation

The evaluation framework combines business outcomes, agent performance, and safety and compliance. Business metrics check approval paths, false approvals, false rejections and review efficiency. Agent metrics use RAGAS for tool-call order, goal accuracy and topic adherence. Safety metrics check policy, groundedness and audit completeness. Metrics needing an LLM are constructed when their evaluator runs, so merely creating evaluator factories does not require credentials.

The faithfulness comparison needed more care than supplying an answer to a judge. The live runner originally omitted the model’s risk explanation, while its grounding record omitted legitimate reviewer metadata. The revised runner includes the explanation, validation result and budget fields in the answer. It gives the judge a separate snapshot of execution facts, configured policy, requester claims and actual reviewer submissions. Editing the candidate answer cannot change that snapshot. Recorded comments establish what a reviewer submitted; they do not make the reviewer’s business or policy claims true.

Four positive/negative control pairs checked whether the judge could detect an invented policy, an incorrect department budget and fabricated approval history, including an error surrounded by genuine metadata. All four checks passed. The mixed record showed how correct timestamps and other fields can dilute an average even when the false reviewer is identified. Its check therefore requires explicit identification of the injected reviewer or stage as well as a lower score. The comparison also labels reviews as performed and budget figures as configured references. Unsupported statements and the judge’s reasons remain available, including deductions that appear inconsistent with the evidence.

The dataset generator produced six normal cases and six edge cases, which were checked against the actual graph and uploaded to LangSmith. This process caught a generated edge case whose expected path incorrectly omitted finance review after an over-budget medium-risk request. The generator now compares labels with an independent policy reference, asks the LLM to repair inconsistent output, and raises an error after three unsuccessful attempts. Generated evaluation data needs validation just as much as generated agent answers do.

## Bonus Features Attempted in Deliverable

**Parallel approvals.** An opt-in bonus mode sends high-risk requests to independent manager and finance graph tasks at the same time. Both interruptions exist before either response is required, and a join waits for both decisions. Either rejection blocks approval. Tests verified Finance finishing first, batched responses, all rejection combinations and recovery after reopening a partially completed checkpoint. The default sequential workflow remains available, and low, medium and critical routes retain their original policy.

**Live dashboard.** The former placeholder panels now read persistent backend activity. The dashboard refreshes every two seconds and shows pipeline totals, waiting review stages, request history and per-request audit details. Progress records stage starts as well as completions, and refresh failures are shown rather than silently presenting stale figures as current.

**Persistent audit trail.** A separate SQLite database records each run’s ID, stage events, review pauses, reviewer roles, timestamps, comments and decisions. A JSON download makes the records inspectable independently of the chat. A backend restart preserved all three browser walkthrough runs: two approvals and one rejection. This is durable local coursework evidence, not an authenticated or tamper-proof production ledger.

**Notification simulation.** Each review pause creates one email preview and one Slack preview in the same transaction as its audit event. Replayed pauses do not create duplicate previews. Ten simulated notification records survived the restart across the three walkthrough requests. No messages were sent to external recipients. Reviewer identities in the demo are role labels, not separately authenticated people.

## Key Learnings

Human-in-the-loop behavior depends on reliable state, validated and correctly addressed decisions, persistence and clear evidence for the reviewer—not only on displaying an approval button. Most of the changes made to the user interface were made to ensure that there was clarity in the underlying facts, so that the decision-making human would have what they needed to know properly (as opposed to just taking it on faith that all the tests were cleared). Parallel review adds a further requirement: independent work must be combined safely before a final outcome is reached.

Passing tests and high evaluator scores are useful only when the scope of each check is clear. The browser walkthrough and live graph runner supplied evidence that reference-only scoring could not provide.

A review can uncover issues that broad tests miss. The decimal-masking defect and mislabeled generated edge case both became concrete regression checks. The interface review also exposed missing business-case evidence and unexplained policy language, which were addressed in the form and review dialog.

An evaluation result is (obviously) itself an output to examine. Positive and negative controls, independent grounding evidence and claim-level explanations made the judge’s limitations visible. A high aggregate score can coexist with an important fabricated detail, so the score alone should not decide whether a financial workflow is safe.A classification model, some type of deterministic or heuristic rubric for additional qualification, some type of independent fact validation, or other types of supporting entities (perhaps a RAG-based infrastructure or something similar) are probably necessary for a production workload to have enough facts to evaluate whether the statements within the application/request actually correspond to the truth or are not representative.

## Ideas for Improvement

I think the next logical set of improvements would be reviewer authentication and authorization, deterministic minimum review requirements alongside the LLM’s classification, and stronger handling of model, network and restart failures. The dashboard, durable audit trail, parallel routing and notification simulation are now implemented, so the remaining work is to harden those features rather than treat them as future additions.

I would also investigate the weaker topic-adherence cases and remaining faithfulness deductions, use field-aware redaction, and expand adversarial and concurrent-request testing. The separate audit database still needs access control, retention rules and tamper evidence for production use. Real notification delivery would need consent, destination verification and retry handling; the assignment implementation deliberately remains a simulation.
