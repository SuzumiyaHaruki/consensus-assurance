Codex implementation task: freer investigation, stronger executable evidence
0. Execute this change on an isolated branch
Repository: SuzumiyaHaruki/consensus-assurance
Reviewed base: c6cbd1b3dbae9abe6503d3ec83e42d17cfadd161
Branch: refactor/evidence-first-audit
Current method: audit-products-v59
Proposed successor: audit-products-v60 (verify that this identifier is unused).
This is an implementation request, not a request for another design proposal. Inspect the code, implement the refactor, remove superseded mechanisms, test it locally, commit, and push the branch. Do not merge into or push changes directly to main.
The user explicitly authorizes this branch, its implementation commits, and its push. The user will run the new Astra and DeepSeek experiments afterward. Do not start paid model calls, a new autonomous target audit, or a model-dependent acceptance test as part of this implementation. Existing local unit/integration tests and synthetic execution tests are in scope. Do not bypass a service refusal or expand execution authorization.
Branch status at handoff
The reviewer verified that main points to the reviewed base and attempted to create this branch through the connected GitHub integration. GitHub returned 403 Resource not accessible by integration; repository metadata reports push: false. No remote branch or implementation commit was created by that attempt. Use the user's normal authorized local Git environment. Do not look for credentials in files or try another identity to bypass that restriction.
Read AGENTS.md and any applicable nested instructions first. This request expressly changes the old initial-overview gate and mandatory representation/step sequencing described in D2–D4 and the corresponding paragraphs. Update those instructions as part of the refactor. It does not waive source protection, execution isolation, evidence integrity, model/service permissions, or the existing prohibition on unauthorized publication.
Check for local edits and an existing branch before running the following operations. Do not reset, discard, or overwrite user work. If necessary, use a separate Git worktree.
git status --short
git fetch origin
# Confirm the reviewed base and whether the proposed branch already exists.
git show --no-patch --oneline c6cbd1b3dbae9abe6503d3ec83e42d17cfadd161
git ls-remote --heads origin refactor/evidence-first-audit

# Only for an absent branch and a clean working tree:
git switch -c refactor/evidence-first-audit c6cbd1b3dbae9abe6503d3ec83e42d17cfadd161
git push -u origin refactor/evidence-first-audit
If the branch exists, inspect its head and continue without resetting or force-pushing. If main has advanced, report the difference and use the reviewed base unless the additional changes have been reviewed for this refactor. Record the actual base in the completion report. A genuine write-permission error must be reported, not represented as a successful push.
Keep this task and the implementation notes in developer-facing documentation, outside the runtime resource manifest and outside the target snapshot supplied to audit agents.
1. Outcome and scope
Replace the current representation-led workflow with source-grounded investigation whose conclusions are constrained by evidence. The system must remain recognizably a CFT audit method, not merely a new name for the plain baseline.
The stable method has three components:
1. Selective understanding. Use consensus formation/progress and context/authority transition as complementary reading and investigation guides. Develop the broad picture and local details together.
2. Causal investigation. For a concrete suspicion, trace what produces the relevant state or message, what consumes it, and what conditions justify the consumer's behavior. Check enclosing protections as well as the local function.
3. Evidence-driven correction. Use source reasoning and actual execution to eliminate alternative explanations, establish the necessary history and observe the claimed result. Correct the relevant understanding and later decisions when evidence contradicts them.
The model chooses the order, granularity, and next useful action. It does not choose whether missing evidence has magically become established.
Loosen: mandatory global-map readiness, mandatory principal-Fact decomposition, redundant per-stage submissions, and lifecycle bookkeeping that does not improve execution or evidence.
Strengthen: the actual producer/history/observation work needed for the current claim, and delivery of concrete feedback about remaining gaps.
Reduce: production code, schema surface, default method text, duplicated state and obsolete tests. This branch must replace the retired workflow, not add a second controller alongside it.
Outside this change
- Do not change baseline/task.md, baseline prompts, the baseline runner, its tool capabilities, or its scoring treatment to make the full system look better.
- Do not modify target protocol code, target dependencies, or the historical runs/ and baseline/runs/ archives.
- Do not inject known findings, historical successful harnesses, target-specific heuristics, or this development discussion into fresh autonomous runs.
- Do not change model names, reasoning effort, providers, catalogs, authentication behavior, or native Codex context management as a hidden part of this method change.
- Do not add a Manager, a reviewer Agent, model-strength classifier, semantic score, reachability boolean classifier, formal-model backend, or automatic paper-level CFT/root-cause classification.
Final defect validity, CFT relevance, deduplication, and paper scoring remain human offline responsibilities. Internal review helps the ongoing investigation; it is not a certified verdict.
2. What the current code actually does
These are confirmed starting points, not a claim that every nearby line is redundant:
Starting point	Current responsibility	Change required
workflow/audit_spec.py::require_overview and its callers in workflow/audit.py::candidate	Reject a new default focused question without a usable two-line overview	Remove this admission gate and the directed-question exception needed solely to bypass it
audit_spec.py::validate_question	Requires one principal Fact and corresponding Behavior/Activity/lifecycle associations	Make the map optional; remove one-Fact and mandatory core-label admission rules; validate references only when supplied
core/submissions.py, resources/tasks/audit.md	Require complete product shapes; specialized revision rules and repeated question payloads	Reduce the public submission surface; support a direct local investigation/check and concise updates
audit.py::candidate	Pauses other active/escalated questions when selecting another one	Remove automatic semantic state changes caused only by a focus switch
audit.py::validate_check_revision, workflow/encoding.py, semantic feedback routes	Distinguish ordinary repair, encoding changes and F2/F3/F4-style paths	Consolidate executed revisions while preserving immutable prior evidence and attribution
ResearchSubmission, ReviewSubmission	Research/map and review are separate product shapes; review cannot carry a map	Allow a coherent result review and relevant knowledge correction together without a mandatory additional handoff
core/config.py::Budget, workflow/research.py::capacity, budget consumers	Separate limits on investigations, revisions, reviews and graph objects as well as real resource limits	Retire quotas tied only to eliminated bookkeeping; retain real time/call/execution limits
audit.py::prompt, research.py	Most detail is behind the research index	Directly deliver a short last-result/current-gap summary; do not resend the whole graph
resources/task-skills.json	Loads v59 method resources	Replace the loaded method with a smaller coherent v60 contract; remove retired resource references


Already available: unrestricted authorized source browsing/editing within Codex, ExploreSubmission, combined Candidate/Obligation/Check submission, same-session continuation, fixed clean-copy execution, and versioned evidence. Reuse these capabilities. Do not build parallel replacements or claim they are newly introduced.
3. Target workflow
The following is a conceptual cycle, not a required sequence of API calls:
Broad orientation <---- local source relationships and corrections
       |                                ^
       v                                |
Concrete suspicion -> discriminating reading or experiment
       ^                                |
       |                                v
Next useful question <- observed result, actual remaining gap,
                        and targeted correction of understanding
A model may start a sourced local inquiry or run a bounded experiment while the broad map is absent or incomplete. It may later add the parts of the map that are useful. An explained suspicion can end through source reasoning without a ceremonial test. A difficult question can remain open while another is investigated. An experiment is not required to produce a defect.
3.1 Sourced questions without a complete map
Refactor the existing AuditQuestion/Candidate path rather than introducing a second LightCandidate or FastAudit hierarchy.
- The minimal persisted question identifies the concrete uncertainty and its captured source basis. A useful next discriminator may be prose in the same record.
- Behavior, Fact, Activity and overview references are optional navigation. When present, keep reference integrity and the actual version of the referenced knowledge.
- Remove the requirement for exactly one fact_ids item and the requirement to manufacture A1/A2 tags through auxiliary Behaviors before a local question is allowed.
- Retain the substantive CFT direction in the method instructions. Do not replace the removed structural gate with a keyword classifier or a compulsory consequence score.
- Do not require a fully formed obligation before reading, exploring, or saving an unresolved question.
- For an update to an existing question, allow referring to its ID and changing the relevant fields; do not require copying its entire unchanged explanation through every submission.
- Existing directed_question remains a real user task boundary and completion condition. It is no longer the only way to use a proportionate local understanding boundary.
3.2 Optional, useful shared understanding
Keep the distinction between Behavior (actual conditional behavior), Fact (what that behavior establishes), and Obligation (what must hold under an applicable contract). Do not require one universal decomposition of the repository.
A map should preserve distinctions that matter to the current inquiry: different guards and error paths, persisted versus published state, notification versus completion, object identity, membership/support qualification, and context changes. Its granularity can expand when investigation needs it.
- A partial map can be saved and consulted without a usable certificate. Remove readiness-only status machinery where it has no remaining use; do not rename it into another gate.
- Independent added knowledge should not require impact declarations for unrelated old objects.
- Updating a premise that is actually used by a saved conclusion must retain a sourced explanation and identify the affected interpretation. Preserve the old basis. Do not silently reinterpret historical observations using the latest map.
- Do not invalidate every result sharing a Fact, Activity or term name. Shared vocabulary is not a dependency.
- Do not force a map-cleanup turn, a map write on every iteration, or an extra translation/summary turn.
- Collapse redundant learning labels such as a self-declared understanding=updated when the actual note/map change already records what happened. Keep substantive answers and current remaining questions, not another completion flag.
Reuse the existing map differencing and attribution machinery where it still has a job. Do not add an automated knowledge-extraction service to recreate a mandatory full graph from free-form reports.
3.3 Fewer handoffs, one execution path
The basic successful path must be possible without preliminary map-building submissions:
Read source -> submit a sourced local claim and complete check together -> controller executes -> model receives the real result -> review/correct/continue.

A setup/compile error can be repaired and resubmitted without rebuilding the question or obtaining semantic permission to change unrelated fixture plumbing.
Use one existing clean-copy execution path for exploration and formal checks. A thin evidence wrapper can distinguish the role of an execution, but do not duplicate compilation, sandbox construction, deadlines or process cleanup.
Allow a result explanation, relevant knowledge update, and a ready follow-up action to be handed off coherently. Reuse the existing preparation/acceptance functions. At most one newly requested target execution is needed per controller operation; do not introduce a general batch language, action DAG, queue manager, or an additional scheduler merely to avoid a review-only turn.
No new in-turn MCP service is required for this refactor. The critical change is removing unnecessary research prerequisites and separate products, not creating another tool stack. Ordinary authorized Codex work remains autonomous; fixed execution results retain their controller-owned identity.
3.4 Focus, pauses and children
A focus pointer is navigation, not proof that all other questions are paused or resolved.
Remove the loop that automatically changes other Candidate statuses solely because another Candidate is selected. Preserve explicit suspension/reopening when the model actually records it. Keep a simple parent/related-question link when useful, but remove the compulsory three-way holds/violated/incomplete impact essay before a child can be investigated. A child's evidence must not automatically settle a different parent claim.
Do not add a model-strength switch: Astra and DeepSeek receive the same method and evidence requirements. Do not relax permissions or truth standards for a supposedly stronger model.
4. Strengthen evidence through investigation, not extra declarations
4.1 Three questions for a proposed conclusion
Concentrate the method and review guidance on these questions, using existing records:
1. Applicable responsibility: What sourced contract or protocol responsibility is being tested, and under which conditions?
2. Actual history: How were the necessary input, state and identities produced in one permitted execution?
3. Actual observation: What did the unmodified implementation do, and why does that observation answer this claim rather than a weaker proxy?
These are logical dependencies, not three mandatory phases or a new form to fill on every turn. A Candidate may investigate any of them. Do not add a compulsory reachability_proved/safe_to_confirm self-certification field.
4.2 Prefer environmental control over protocol-state fabrication
Prompts and examples should guide the model to run actual constructors, proposals, message producers, storage and handlers while controlling the environment: delivery, delay, an allowed failed storage call, timer progression, disconnection, restart, or an asynchronous boundary.
A message emitted by the real producer and delayed without modification is stronger evidence than a manually assembled message containing the result the test needs. A persisted value obtained from real prior calls is stronger than directly setting a promise, vote, committed marker or completion state.
However, do not prohibit synthetic states, internal handlers, small in-process replicas, or local interface tests. They are useful exploration tools. Clearly retain which decisive conditions were supplied by the test. A legal public interface can also admit caller inputs directly; such a local defect need not reproduce a whole protocol deployment.
Keep the fault model explicit. An allowed storage error after prior successful calls is different from rewriting a previously durable value. Transport wrappers must respect the relevant transport contract: labeling an action "delay" does not make arbitrary reordering across a guaranteed FIFO connection valid.
4.3 Make initialization-based evidence practical
For a result whose claim depends on normal protocol reachability, prefer an actual initialization-to-trigger execution. Avoid forcing every experiment to build a new distributed deployment.
- Reuse the target's constructors and test utilities, after checking that they do not bypass the premise under investigation.
- Reuse code that runs a real prefix. Branch a controlled schedule from the produced state when possible.
- A persisted snapshot/checkpoint can shorten a prefix only when it is produced by an allowed history and contains the relevant retained state. It does not stand in for in-flight messages, request/future identity, active workers or membership context that the claim needs.
- Sequential deterministic handler delivery and in-memory transports are acceptable when they preserve the implementation's caller and scheduling contract.
- An initialization-equivalent fixture needs a concrete source-based correspondence for the fields that matter; merely saying "equivalent" is not evidence. When correspondence becomes complicated, run the real prefix instead.
- Do not stitch two independently valid segments together solely because their index/term numbers match. The joint history and object/context relationships must match.
Do not implement a checkpoint platform, schedule DSL, generic replay engine, or automatic backward reachability solver. Use the existing harness files and execution interfaces.
4.4 After a local anomaly, pursue the missing causal link
Make the default follow-up question concrete: Which missing fact would change the current answer?
- A constructed special state: investigate its real producer and prefix.
- A seemingly missing local guard: inspect enclosing admission, serialization, reset or other consumers.
- A response that allegedly contradicts execution: observe the same operation at the promised endpoint.
- An applied-effect claim: record actual Apply/read state, not a Boolean inferred only from entry presence or a quorum counter.
- A liveness claim: inspect the owner of continuing work, queues, callbacks and allowed scheduling; finite waiting alone is not proof of permanent failure.
- An independently supported local interface defect: preserve it without requiring the worst conceivable cluster consequence.
The model may stop pursuing an unproductive premise, retain the gap, and investigate another direction. Do not require endless attempts or a finding quota. Do not promote a missing producer/history condition to an "independent scope" note when the current conclusion relies on it.
4.5 Mechanical enforcement has a limited but important role
Keep execution completion, observed prerequisite matching, identity correlation, fixed source/claim/checker versions, and open-issue linkage distinct from model prose.
- Unreached setup or absent required observations must not yield a confirmed violation or a property-holds conclusion.
- An explicitly unresolved condition necessary to the current conclusion stays unresolved. A no_issue_found statement cannot cancel contrary registered evidence by itself.
- A wider untested consequence does not invalidate an independently established local result.
- Structure validation proves the structure, not source meaning, reachability, or truth. Do not claim otherwise in diagnostics.
- Preserve incomplete exploratory executions and raw outputs. Missing a final model response or a formal assessment must not erase evidence already produced within budget.
The controller cannot generally verify natural-language semantics or infer all necessary conditions. Review must investigate them; tests of the controller must not pretend to prove that the model will reason correctly.
5. Consolidate revision and correction semantics
Retain the safety property of the old machinery, not its many compulsory labels.
Use one recorded successor/revision mechanism for an executed check or investigation: predecessor ID, reason, changed basis, retained source/claim information, and linked execution. Prefer extending revise_check and existing versioned records instead of adding a new revision subsystem.
Remove the requirement that the model first choose between ordinary repair, F2, F3, F4 and checker-encoding correction paths. Delete separate validators/submission fields/modules whose sole remaining purpose is enforcing that taxonomy. Mechanically deriving a diff is useful; demanding several duplicate explanations of the same diff is not.
Preserve these invariants:
- Prior submitted bytes, results, requirements and reviews stay immutable.
- A change to an executed harness, assumptions, observation, oracle or claim cannot reuse the old execution as confirmation of the successor. Execute the changed check and review the actual new basis.
- A correction to the surrounding understanding alone does not force rerunning an unaffected execution. Keep the old interpretation visible and review only the actual dependency change.
- Replacing or weakening a tested assertion is visible as a new version; it cannot silently erase an old failure or dispute.
- Resolving an issue identifies that issue and its supporting source/execution. New links do not auto-resolve unrelated issues.
- Competing drafts use existing operation/version identity and transaction behavior. Do not introduce a second approval system or new per-stage hash gates.
Audit core/proposals.py, core/submissions.py, workflow/audit.py, workflow/encoding.py, graph/feedback paths and their imports together. Internal Unit/binding structures may remain where they truly serve execution/source ownership; stop forcing the model to author redundant aliases and derive purely mechanical associations. Remove unused structures after the simplification, rather than renaming the old graph and keeping every route alive.
6. Remove superseded code and tests in the same branch
Before editing, make a short responsibility inventory: keep / replace-and-delete / unchanged. Put the final inventory in the completion note, not in a new runtime registry.
The deletion inventory must include:
Retired responsibility	Required cleanup
Usable-overview admission	Function/callers, readiness-only diagnostics and scheduling hints, directed-only bypass, tests asserting rejection, instructions requiring it
Exactly one principal Fact and forced core labels	Field cardinality and mandatory-edge validation, duplicate source-overlap rules used solely for admission, fake-map fixtures, CLI/schema help
Focus switching as automatic pause/release	Status mutation, automatic release metadata with no remaining consumer, pause bookkeeping tests
Compulsory child outcome taxonomy	Required result-implication dictionaries and their validation/prompt text; retain only useful causal links
Repeated whole-question and separate knowledge/review handoffs	Redundant fields, duplicate copies, shape-only validators and fixtures; preserve actual attribution
Specialized repair taxonomy	Orphaned encoding/semantic-revision routes, dispatch branches, fields, tests and resource explanations
Research-product quotas	audit_units, revisions, semantic_reviews, graph_objects where they only cap these products; remove the corresponding charging, admission and capacity branches instead of silently raising limits
Mechanical repair penalties tied to the retired stages	Inspect repair_attempts and related counters; remove stage/semantic churn controls with no remaining necessity. Preserve bounded handling of real process/client failures under existing budgets
Redundant method prose and deprecated loaders	Replace the old text, remove unreferenced resources/manifests/package-data references, and simplify help and docs


Retain total_seconds, model-call limits, target-execution limits, per-call deadlines, real cancellation/refusal handling and exact same-session continuation. A local inability to complete a claim must not consume a new artificial budget category.
For old configs, use existing strict schema/version checks to issue a short, actionable incompatibility error. Generate fresh templates for new runs. Do not maintain v59 and v60 live engines, an enable_v60 flag, model-specific compatibility paths, or an automatic historical migration service. Old runs stay readable in their archived files; executing/resuming them uses their original Git revision. A new method must not silently resume an old run under changed rules.
Code-size accounting
Report production Python, shipped method/schema resources, and tests/fixtures separately against the actual base. Report both added/deleted lines and before/after totals; also compare the bytes/tokens or characters of the actual loaded default method text using one consistent local metric.
The expected result is a meaningful net reduction in the affected production workflow and its obsolete tests. Do not meet a cosmetic target by minifying code, deleting necessary safety coverage, moving files to another directory, or deleting archived experiments. If one category grows, identify the concrete retained responsibility and the superseded code removed elsewhere. No arbitrary percentage is required, but an additive wrapper around all old machinery does not satisfy this task.
7. Preserve execution and experiment boundaries
Leave baseline production files and historical experiments unchanged. If a neutral shared component is genuinely touched, inspect its baseline callers and run the relevant regression; do not make the baseline import the full research workflow.
Keep:
- Captured source and trusted prompts read-only to model actions; separate writable drafts.
- Credential/environment exclusion and existing filesystem/symlink boundaries.
- Target execution only under the approved isolation, with descendant cleanup on timeout/cancellation/disconnection as appropriate.
- Same native session within a run; fresh sessions between independent runs.
- Explicit model/provider/catalog/CLI/toolchain settings and captured execution inputs.
- Raw output and artifact association, including failures and unfinished work.
- Distinct process outcome, actual observation and semantic interpretation.
- Existing Go, Rust/Cargo and other supported execution backend behavior. Keep protocol-specific differences in target adapters/configuration, not the controller or method.
Do not weaken permissions to enable the freer workflow. Do not reintroduce host/user skills, arbitrary network access, repository history lookup or automatic issue search into model inputs.
8. Deliver useful feedback without another control layer
Update the existing continuation prompt/index so that the model directly receives a small last-operation summary: accepted/rejected/executed state, the relevant execution/result locator, a concrete known blocker if present, and whether an identical adjacent handoff changed nothing.
Do not resend the full map and method each turn. Do not compute a novelty score. A source explanation, corrected observation, new causal prefix, negative result or useful note is progress even without a new defect or a map version.
Existing adjacent-duplicate detection can cover an identical unchanged map submission when the actual inputs and relevant state are unchanged. Keep this informational; do not stop after N repetitions, force a test quota, or manufacture an obligation to fill time.
Open audits still continue useful work until their declared resource boundary or a genuine interruption. A preconfigured finite directed task can complete. At expiry, preserve existing work; do not request an extra billable wrap-up call.
9. Replace the method text and update project instructions
Update AGENTS.md, README.md, docs/审计方法.md, docs/运行工作流.md, affected configuration/environment help, runtime resources and the authoritative manifest coherently.
English: agent instructions, schemas/semantic fields, identifiers and comments. Chinese: human-facing explanations and reports.
Keep one concise substantive method description and a minimal tool/submission reference. Merge or remove overlapping guide/reference material after checking actual manifest loading. The runtime method should express:
- broad and local understanding refine one another;
- actual production versus required consumption, including context changes;
- source-backed hypotheses are revisable;
- actual prefix/fault/identity/endpoint evidence determines the scope of a result;
- new evidence changes the relevant understanding and the next discriminator.
Do not load developer examples containing historical findings. Use only small synthetic examples for regression and keep them in tests/fixtures, not as runtime discovery answers.
Bump the actual loaded method manifest, not only the displayed report version. Verify the new version and loaded paths appear in new run inputs. Reject incompatible resume before any model call or state mutation. Preserve original archive contents and do not rerender them under the new interpretation as though they were new experiments.
10. Acceptance: exercise the behavior, not a new pile of tests
Read the existing suites and reuse their nearest entry points. Delete tests whose only purpose was locking in a retired policy. Keep a small number of end-to-end cases and parameterize cheap validation differences.
Required behavior	Minimal evidence
Early local inquiry	A sourced Candidate and combined claim/check are accepted with no usable global overview and no principal Fact; an existing source/permission violation still fails
Local and global learning coexist	Save a partial map or feedback, perform a local check, and later refine related understanding without a fabricated full map
Free reselection	Switching questions retains other questions and evidence without automatic semantic pause/closure
Conditional exploration then real prefix	In a tiny neutral fixture, run a constructed-state probe with its gap; then a successor using actual producers and the real observed endpoint. Preserve both executions and do not retroactively confirm the first
Actual observation is required	Setup failure, missing prerequisite, identity mismatch or a missing required endpoint cannot be promoted by a successful process exit or an unsupported no_issue_found
Revision integrity	Changed harness/oracle/claim gets a visible successor and new execution; old evidence is not overwritten or reused as new confirmation; unrelated results remain untouched
Feedback reaches the next call	A scripted/replay Agent sees the actual result and known missing link in the next same-session input; no assertion that this proves real-model reasoning
Safety and compatibility	Existing read-only/credential/isolation/cleanup checks, target package/crate handling, and incompatible-resume checks continue to behave correctly


These are coverage responsibilities, not a command to add one new test file per row. Prefer adapting existing workflow tests, tests/unit/test_audit_capabilities.py, graph/feedback/reporting tests, and execution tests. Preserve real lifecycle tests when they exercise different cleanup paths.
Use the repository's environment and pytest configuration. testpaths currently names tests only; baseline regressions must be selected explicitly if a shared neutral component changes. Inspect model-call tests and their opt-ins before executing broad suites; do not accidentally enable live credentials/calls. Report exact commands and results, with skipped real-tool paths identified.
A missing local tool or OS isolation capability is an environment limitation, not a reason to weaken isolation or add a skip hiding a new failure. Reproduce a representative failure on the base when needed. Do not conflate mock/replay success, native CLI compatibility, and actual model investigation.
11. Prepare, but do not launch, the two-model experiments
After tests, provide concise Chinese instructions for the user to start new full-system runs on this branch using the existing CLI and locally authorized target paths.
- Keep one v60 method for both models. Retain the native Astra and explicit DeepSeek provider configurations; do not silently change effort levels.
- For a direct continuation of the recent comparison, document Astra low and DeepSeek high with a proposed common 3,600-second total budget, 900-second maximum Agent turn and 600-second maximum target action. Have the user explicitly choose real call/execution caps high enough not to become accidental product quotas. Do not alter shipped neutral defaults merely to obtain more work.
- Committed templates remain unauthorized (allow_agent_materials: false, allow_experiments: false); generate local ignored *.run.yaml files only through the existing explicit authorization workflow. Never commit credentials or local permission overrides.
- Freeze target commit, CLI/catalog, toolchain, features, source visibility and declared cache policy. Run sequentially or use declared resource isolation, not uncontrolled simultaneous contention.
- Keep the baseline unchanged. An old v59/full or Astra/DeepSeek result is historical context, not a new matched comparison. When measuring method gain, compare the same model under declared comparable conditions.
- Start fresh sessions and run directories. Do not feed historical reports, existing bugs, known reproducers or this task into autonomous discovery.
- The user decides whether/when to run the paid experiments. Do not retry cyber refusals or treat them as completed zero-finding audits.
Retain the existing raw data needed to compare first useful execution, first sufficient witness, valid independent findings, incorrect conclusions, further useful investigations and actual resource use. Prefer offline analysis of existing logs to a new runtime analytics subsystem. Native usage may be cumulative; do not sum snapshots without establishing semantics. Internal confirmed, tool counts and map sizes are not final defect counts.
12. Commit sequence and completion criteria
Use a few coherent commits on the single branch, for example:
1. refactor: remove overview and representation admission gates — simplify question/map use and retire their tests/instructions together.
2. refactor: unify investigation revisions and handoffs — simplify lifecycle/product paths, remove superseded quotas and redundant state, preserve evidence identity.
3. feat: focus follow-up on executable history and actual observations — replace method text, deliver concise feedback, update focused regression fixtures.
4. docs: record v60 migration and experiment commands — only if needed as a separate commit; do not create many cosmetic commits.
Adapt boundaries to keep the branch testable. Do not retain the old engine behind a feature flag to keep intermediate commits green.
The final response to the user must contain:
- remote branch URL and pushed commit SHA(s), or the exact write blocker;
- actual base and loaded method version;
- a short list of deleted responsibilities, not only new capabilities;
- before/after production, runtime-resource and test size measurements;
- exact tests run, pass/fail/skip counts and untested paths;
- confirmation that baseline production behavior and historical archives were not changed;
- new-run commands/config guidance for Astra and DeepSeek, without starting them;
- concrete remaining implementation issues, if any. Do not substitute an assertion that the model will now be more capable.
Do not declare completion with only a proposal, a new prompt file, renamed old machinery, or a new wrapper around the old gates. Completion means the new path is exercised, the retired path is removed, and the user can run new experiments from the pushed branch.
Source basis for this task
The design changes above are user-authorized proposals, not claims that the existing code already implements them. The inspected base is fixed; these links are developer references and must not be loaded into autonomous target audits.
- Repository development contract
- Current map/question validation
- Current acceptance, revision and execution flow
- Current file-backed products
- Current configuration and resource categories
- Actually loaded method manifest
- Current model-facing product instructions
- Human-facing method
- Execution/environment commands
- Test configuration