# GridWise — research base (2025–2026)

Literature, code, and model links gathered on 18 September 2026 for the BUP CSE Fest 2026
preliminary. Selected for one criterion: **can this be used, cited, or defended in a 4-hour
build and a 3-minute architecture video?** Everything below is either a top-tier venue paper,
a runnable repository, or a pullable model.

Companion document: [ARCHITECTURE_CLAMP.md](ARCHITECTURE_CLAMP.md) — the refined architecture
and the new algorithm that these references support.

Legend: **[TIER-1]** top venue · **[CODE]** public repo · **[HF]** Hugging Face · **[USE]** directly
reusable in this build · **[CITE]** cite in README/video, do not implement.

---

## 1. Closest prior work — read these first

The single closest published system to this challenge. Know it, and know how the proposed
architecture differs, because a judge who knows the literature will ask.

| Paper | Venue | Why it matters | Link |
|---|---|---|---|
| **DARC: A Constraint-Diagnostic LLM Agent Framework for Day-Ahead Dispatch of Campus-Level Integrated Energy Microgrids Under Natural-Language Preferences and Forecast Uncertainty** | *Energies* 19(16):3817, Aug 2026 | Campus microgrid, day-ahead horizon, **natural-language operator preferences → MILP constraints**. Decompose → Resolve (LLM) → **Project** (repair candidate schedule) → **Check** (mathematical facts ground a Critic's feedback). Beats point-forecast MILP and interval-robust MILP on realized feasibility. Pyomo + HiGHS. | [doi:10.3390/en19163817](https://doi.org/10.3390/en19163817) |
| **Agentic AI Home Energy Management System** | arXiv 2510.26603 / *Energy & Built Environment* | Orchestrator + 3 specialist agents, ReAct, **validated against a MILP oracle**. Llama-3.3-70B hits MILP-optimal; Qwen-3-32B and GPT-OSS-120B fail on multi-appliance coordination. Direct evidence that **model choice dominates** on constraint-coupled scheduling. **[CODE]** | [arXiv](https://arxiv.org/abs/2510.26603) · [github](https://github.com/RedaElMakroum/agentic-ai-hems) |
| **LLMs for Agentic Home Energy Management** | arXiv 2607.04569 (Jul 2026) | Tool-calling ReAct agent vs. MILP oracle under dynamic tariffs. **Native function calling beats text-parsed actions.** Agents capture 96.7–98.0% of oracle savings. **[CODE]** | [arXiv](https://arxiv.org/abs/2607.04569) · [github](https://github.com/sokistar24/ecohome-experiments) |

**What DARC does not do, and we will:** DARC *repairs* a single interpretation's schedule
(projection + critique). It commits to one reading of the note and then fixes the schedule.
It never hedges across *several* plausible readings of the same sentence. That gap is the
opening — see [ARCHITECTURE_CLAMP.md §3](ARCHITECTURE_CLAMP.md).

---

## 2. Natural language → optimization model (the NL4Opt lineage)

This is the academic frame for "operator note → structured directive". Cite it to show the
work sits in a real research area rather than being ad-hoc prompt engineering.

| Resource | Venue / type | Use | Link |
|---|---|---|---|
| **A Survey of Optimization Modeling Meets LLMs: Progress and Future Directions** | **IJCAI 2025, Survey Track** **[TIER-1] [CITE]** | The one citation to anchor the README. Full stack: data synthesis, fine-tuning, inference frameworks, benchmarks. Also **audits benchmark quality and finds a surprisingly high error rate** — a useful, quotable caution about trusting reference labels. | [IJCAI PDF](https://www.ijcai.org/proceedings/2025/1192.pdf) · [arXiv 2508.10047](https://arxiv.org/abs/2508.10047) · [portal](https://llm4or.github.io/LLM4OR) |
| **ConstraintLLM: A Neuro-Symbolic Framework for Industrial-Level Constraint Programming** | **EMNLP 2025 Main** **[TIER-1] [CODE]** | Constraint-Aware Retrieval Module inside a Tree-of-Thoughts loop with guided self-correction. Releases **IndusCP** (140 industrial CP tasks). The closest published articulation of "LLM proposes, symbolic solver disposes". | [ACL Anthology](https://aclanthology.org/2025.emnlp-main.809/) · [github](https://github.com/william4s/ConstraintLLM) |
| **LLMOPT: Learning to Define and Solve General Optimization Problems from Scratch** | **ICLR 2025** **[TIER-1] [CODE]** | Universal *five-element* formulation (sets, params, vars, constraints, objective) + model alignment. 97.3% on NL4Opt. The five-element idea maps cleanly onto our fixed 6-directive schema. | [github](https://github.com/antgroup/LLMOPT) |
| **ORLM: A Customizable Framework in Training Large Models for Automated Optimization Modeling** | **Operations Research (INFORMS)** **[TIER-1] [CODE] [HF]** | OR-Instruct synthesis; 7B open models beating GPT-4 prompting. Weights are public. | [INFORMS](https://pubsonline.informs.org/doi/10.1287/opre.2024.1233) · [arXiv 2405.17743](https://arxiv.org/abs/2405.17743) · [github](https://github.com/Cardinal-Operations/ORLM) · [HF org](https://huggingface.co/CardinalOperations) |
| **Solver-Informed RL (SIRL): Grounding LLMs for Authentic Optimization Modeling** | arXiv 2505.11792 | Uses **solver execution output as a verifiable reward**. Same principle we use offline: the solver, not a human rubric, decides whether an interpretation was right. | [arXiv](https://arxiv.org/abs/2505.11792) |
| **CP-Bench: Evaluating LLMs for Constraint Modelling** | arXiv 2506.06052 | 101 CP problems. Finding worth repeating in the video: **Python-embedded modelling (CPMpy) beats MiniZinc for LLM accuracy** — favour a Python-native constraint representation, which is what our compiler is. | [arXiv](https://arxiv.org/abs/2506.06052) |
| **Text2Zinc** | arXiv 2503.10642 | Cross-domain NL→MiniZinc dataset. Useful as a source of *paraphrase* patterns for the eval set. | [arXiv](https://arxiv.org/abs/2503.10642) |
| **OptiMUS: Scalable Optimization Modeling with (MI)LP Solvers and LLMs** | **ICML 2024** **[TIER-1] [CITE]** | The origin point for agentic NL→MILP. Older, but every reviewer knows it. | [PMLR](https://proceedings.mlr.press/v235/ahmaditeshnizi24a.html) |

---

## 3. Structured generation and guardrails (the "LLM output is untrusted data" layer)

The problem statement mandates deterministic validation of model output. These are the papers
and libraries that make that layer fast and defensible.

| Resource | Venue / type | Use | Link |
|---|---|---|---|
| **XGrammar: Flexible and Efficient Structured Generation Engine for LLMs** | **MLSys 2025** **[TIER-1] [CODE] [USE]** | Grammar-constrained decoding at near-zero overhead; default backend in vLLM, SGLang, TensorRT-LLM. **Guarantees the JSON shape so guardrails only have to check semantics.** | [arXiv 2411.15100](https://arxiv.org/abs/2411.15100) · [github](https://github.com/mlc-ai/xgrammar) |
| **CRANE: Reasoning with Constrained LLM Generation** | **ICML 2025** **[TIER-1] [USE]** | Proves *why* hard grammar constraints degrade reasoning, then interleaves free and constrained windows via delimiters. Up to +10 pts on symbolic reasoning. **Directly applicable**: let the model reason about "reduced *by* 80%" in a free-text scratch field, then constrain only the JSON block. | [PMLR v267](https://proceedings.mlr.press/v267/banerjee25a.html) · [arXiv 2502.09061](https://arxiv.org/abs/2502.09061) |
| **Let Me Speak Freely? A Study on the Impact of Format Restrictions on LLM Performance** | **EMNLP 2024 Industry** **[TIER-1] [CITE]** | The empirical result CRANE explains. Format restriction helps classification, hurts reasoning. Our task is *both*, which is exactly why the two must be separated in the prompt. | [ACL Anthology](https://aclanthology.org/2024.emnlp-industry.91/) |
| **JSONSchemaBench** | arXiv 2501.10868 | Efficiency / coverage / quality of constrained decoding across 10K real schemas. Use it to justify the schema design (flat, small, enum-first). | [arXiv](https://arxiv.org/abs/2501.10868) · [OpenReview](https://openreview.net/forum?id=FKOaJqKoio) |
| **Outlines** | library **[CODE] [USE]** | FSM-based constrained decoding for local/self-hosted models. | [github](https://github.com/dottxt-ai/outlines) |
| **Instructor** | library **[CODE] [USE]** | Pydantic-native structured output over OpenAI / Anthropic / Gemini with automatic revalidation-retry. The pragmatic choice for a hosted-API submission. | [github](https://github.com/567-labs/instructor) |

---

## 4. Ambiguity and uncertainty over interpretations (foundation of the new algorithm)

This cluster is what turns the submission from "good engineering" into something with a claim.
A hidden operator note is a *paraphrase*; paraphrase means genuine interpretation uncertainty.

| Resource | Venue / type | Use | Link |
|---|---|---|---|
| **Detecting hallucinations in large language models using semantic entropy** | **Nature, 2024** **[TIER-1] [CITE]** | Farquhar, Kossen, Kuhn & Gal. Sample K generations, cluster by **meaning** not tokens, take entropy over clusters. The paper our constraint-space voting generalizes — except we get *exact* equivalence instead of NLI-approximate clustering, because our semantics are executable. | [Nature](https://www.nature.com/articles/s41586-024-07421-0) |
| **Disambiguate First, Parse Later: Generating Interpretations for Ambiguity Resolution in Semantic Parsing** | **Findings of ACL 2025** **[TIER-1] [CITE]** | Saparina & Lapata. LLMs have a strong **preference bias**: on an ambiguous utterance they emit only the single most likely reading. They generate the *set* of interpretations and validate each **by SQL execution**. Precisely our situation, with the LP playing the role of SQL. | [ACL Anthology](https://aclanthology.org/2025.findings-acl.863/) · [arXiv 2502.18448](https://arxiv.org/abs/2502.18448) |
| **Zero and Few-shot Semantic Parsing with Ambiguous Inputs** | **ICLR 2024** **[TIER-1] [CITE]** | AmP benchmark. Establishes that LLM confidence does *not* track ambiguity — the reason we must not trust a self-reported confidence field. | [arXiv 2306.00824](https://arxiv.org/abs/2306.00824) |
| **Cleanse: Uncertainty Estimation via Clustering-based Semantic Consistency** | GEM @ ACL 2025 | Intra-cluster consistency ratio as an uncertainty score. A cheap, implementable scalar. | [ACL Anthology](https://aclanthology.org/2025.gem-1.25/) |
| **TECP: Token-Entropy Conformal Prediction for LLMs** | arXiv 2509.00461 | Logit-free, reference-free conformal sets over LLM outputs. Usable when the provider does not return logprobs. | [arXiv](https://arxiv.org/abs/2509.00461) |
| **When Can Conformal Risk Control Certify LLM Outputs? Bounds, Impossibility, and Adaptation for Structured Generation** | arXiv 2606.29054 | **Read the caveat, not just the method.** Proves an impossibility frontier, and shows static conformal risk control **fails on 14 of 16 transfer scenarios under distribution shift**. Hidden judge notes *are* a distribution shift from any dev set we write. This is why our threshold is presented as calibrated-and-tuned, not guaranteed. | [arXiv](https://arxiv.org/abs/2606.29054) |
| **PASC: Pipeline-Aware Conformal Prediction with Joint Coverage Guarantees** | arXiv 2605.18812 | Certifies a whole multi-stage pipeline rather than one model call — the right formalism for LLM → guardrail → compiler → LP → replay. | [arXiv](https://arxiv.org/abs/2605.18812) |
| **Uncertainty Quantification and Confidence Calibration in LLMs: A Survey** | **KDD 2025** **[TIER-1] [CITE]** | One-stop citation for the UQ taxonomy (input / reasoning / parameter / prediction uncertainty). | [ACM DL](https://dl.acm.org/doi/abs/10.1145/3711896.3736569) |

---

## 5. Conformal sets → robust optimization (the bridge that makes the hedge principled)

Nobody in cluster 4 feeds their prediction sets to a scheduler, and nobody in this cluster
builds their uncertainty set out of *LLM semantics*. Joining the two is the contribution.

| Resource | Venue / type | Use | Link |
|---|---|---|---|
| **Conformal Uncertainty Sets for Robust Optimization** | **PMLR (COPA) 2021** **[CITE]** | Johnstone & Cox. The canonical result that conformal regions give finite-sample-valid, conservative uncertainty sets that plug straight into a robust program. | [PMLR v152](https://proceedings.mlr.press/v152/johnstone21a.html) · [arXiv 2105.14957](https://arxiv.org/abs/2105.14957) |
| **Learning Polyhedral Conformal Sets for Robust Optimization** | arXiv 2605.08506 (rev. Sep 2026) | Decision-aware conformal sets: shape the set to the downstream objective instead of to raw coverage. Our meet-semilattice is a discrete analogue of exactly this. | [arXiv](https://arxiv.org/abs/2605.08506) |
| **Calibrating Decision Robustness via Inverse Conformal Risk Control** | arXiv 2510.07750 | Picks the *robustness level* from a regret target rather than by hand — the principled version of our hedging-budget knob. | [arXiv](https://arxiv.org/abs/2510.07750) |
| **Automated Reformulation of Robust Optimization via Memory-Augmented LLMs** | arXiv 2605.11813 | LLM-driven robust-counterpart reformulation (LP/SOCP/ECP). Adjacent but distinct: they make the *model* robust, we make the *interpretation* robust. | [arXiv](https://arxiv.org/abs/2605.11813) |

---

## 6. Explanation via LP duals (grounds `plan_summary`, and makes a great video beat)

| Resource | Venue / type | Use | Link |
|---|---|---|---|
| **Explainable LP-MPC: Shadow Price Contributions Reveal MV-CV Pairings** | arXiv 2512.06194 | Recasts LP shadow prices as a **post-hoc attribution mechanism**. We reuse the idea to answer "this note cost the campus X BDT", from duals HiGHS already returns. | [arXiv](https://arxiv.org/abs/2512.06194) |
| **Constraint-Anchored Attribution: Feasibility-Certified Counterfactuals and Bonferroni-PAC Sufficient Subsets** | arXiv 2605.25235 | Decomposes decisions by constraint family via LP-relaxation duals and **certifies** the counterfactuals. Exactly the rigour level to claim for a counterfactual "what if this directive were lifted" number. | [arXiv](https://arxiv.org/abs/2605.25235) |

---

## 7. Operator notes are untrusted input (cheap points in Performance & Reliability)

`operator_notes` is free text that reaches a model which then emits constraints. That is
textbook indirect prompt injection. The rubric awards 2 points for "controlled malformed /
model-provider failure handling and secret safety" — this is how to earn them and say why.

| Resource | Venue / type | Use | Link |
|---|---|---|---|
| **Defending Against Indirect Prompt Injection Attacks With Spotlighting** | Microsoft Research, arXiv 2403.14720 **[USE]** | Datamarking / delimiting / encoding of untrusted spans. **Attack success >50% → <2%** with negligible task cost. Three lines of code in our prompt builder. | [arXiv](https://arxiv.org/abs/2403.14720) · [reference impl](https://github.com/realArcherL/spotlighting-datamarking) |
| **Defeating Prompt Injections by Design (CaMeL)** | arXiv 2503.18813 **[CITE]** | Privileged-LLM / quarantined-LLM split: untrusted data never influences control flow. Our architecture is a degenerate CaMeL — the LLM emits data into a fixed schema and *cannot* reach the solver except through the compiler. Worth one sentence in the video. | [arXiv](https://arxiv.org/abs/2503.18813) |
| **Lessons from Defending Gemini Against Indirect Prompt Injections** | arXiv 2505.14534 | Defence-in-depth evaluation methodology from a production system. | [arXiv](https://arxiv.org/abs/2505.14534) |

---

## 8. Energy-domain background (README credibility, video framing)

| Resource | Venue / type | Use | Link |
|---|---|---|---|
| **Comparative Evaluation of MILP, MPC, and RL for Commercial Battery Dispatch Under Time-of-Use Tariffs** | arXiv 2609.14776 (Sep 2026) | Full-year real data. MILP with perfect foresight = −24.6% cost vs. no storage; MPC recovers 99.2% of it; **SAC-based RL is worse than no storage at all.** The cleanest one-line justification for choosing an exact LP over anything learned. | [arXiv](https://arxiv.org/abs/2609.14776) |
| **A large language model for advanced power dispatch** | **Scientific Reports 2025** **[TIER-1]** | LLM in the dispatch loop, peer-reviewed. | [Nature SR](https://www.nature.com/articles/s41598-025-91940-x) |
| **Grid-Agent: An LLM-Powered Multi-Agent System for Power Grid Control** | arXiv 2508.05702 | Planning agent + **validation agent with sandboxed execution and rollback**. Same separation-of-powers we use; good architectural precedent to name. | [arXiv](https://arxiv.org/abs/2508.05702) |
| **Power Systems Agent Benchmark: Executable Evaluation of AI Agents in Electric Power Engineering** | arXiv 2606.20950 | Executable evaluation harness for power-domain agents. Design source for our own eval runner. | [arXiv](https://arxiv.org/abs/2606.20950) |
| **AI Large Models for Power System: A Survey and Outlook** | *IET Smart Energy Systems* 2025 | Broad survey; one citation for the README's context paragraph. | [Wiley](https://ietresearch.onlinelibrary.wiley.com/doi/10.1049/ses2.70000) |
| **Large language models in renewable energy systems: forecasting, control, policy, fault diagnosis** | *Energy & AI* / ScienceDirect 2026 | Review covering the control-and-scheduling slice. | [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S2949821X26000761) |

---

## 9. Models and weights (Hugging Face)

The LLM must be live during judging and p95 should stay ≤5 s. Both a hosted primary and a
local fallback are worth configuring; the guide explicitly permits a local backup model.

| Model | Size | Why | Link |
|---|---|---|---|
| **Qwen3-4B-Instruct-2507** | 4B | Strong instruction-following and tool-use at a size that serves sub-second on a small GPU with vLLM + XGrammar. The realistic self-hosted fallback. | [HF](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) · [GGUF](https://huggingface.co/Mungert/Qwen3-4B-Instruct-2507-GGUF) |
| **Qwen3 Technical Report** | — | BFCL-v3 function-calling numbers, for the README's model-selection paragraph. | [arXiv 2505.09388](https://arxiv.org/abs/2505.09388) |
| **NuExtract-2.0-8B** | 8B | Purpose-built text→JSON extractor (QwenVL base). A defensible *second opinion* model whose failure modes are uncorrelated with a general chat LLM — useful for the disagreement ensemble. | [HF](https://huggingface.co/numind/NuExtract-2.0-8B) |
| **NuExtract-1.5-tiny** | 0.5B | Qwen2.5-0.5B fine-tune. Runs on CPU. A genuine "provider is down" fallback that still satisfies the LLM requirement. | [HF](https://huggingface.co/numind/NuExtract-1.5-tiny) |
| **NuExtract3** | 4B | Newest of the family, unified extraction + document reasoning. | [HF](https://huggingface.co/numind/NuExtract3) |
| **CardinalOperations (ORLM weights)** | 7B | Open models fine-tuned specifically for optimization modelling. | [HF org](https://huggingface.co/CardinalOperations) |

**Caution on fine-tuned extractors.** NuExtract-class models are trained for *template filling*,
not for the relevance judgement this task needs (`no_op` vs. a real directive) or for the
"reduced **by** 80% ⇒ factor 0.2" inversion. Benchmark before trusting; the guide bans long
training/fine-tuning during evaluation anyway.

---

## 10. Datasets worth mining for paraphrases

No public dataset matches this task. These are sources of *phrasing patterns* for building the
held-out interpretation eval, not drop-in training data.

| Dataset | Content | Link |
|---|---|---|
| **NL4Opt** (NeurIPS 2022 competition) | 1,101 LP word problems, 289 eval | [competition](https://nl4opt.github.io/) |
| **IndustryOR** | 100 real industrial OR problems, incl. **energy** | via [ORLM repo](https://github.com/Cardinal-Operations/ORLM) |
| **IndusCP** | 140 industrial CP tasks (ConstraintLLM) | [github](https://github.com/william4s/ConstraintLLM) |
| **CP-Bench** | 101 CP problems, 241 constraint types | [arXiv 2506.06052](https://arxiv.org/abs/2506.06052) |
| **TimE** | Multi-level temporal-reasoning benchmark — window/interval phrasings | [arXiv 2505.12891](https://arxiv.org/abs/2505.12891) |

---

## 11. What is *not* worth reading for this build

Recorded so nobody spends round time re-deciding.

| Area | Why skip |
|---|---|
| RL / DRL for battery dispatch | [arXiv 2609.14776](https://arxiv.org/abs/2609.14776) measured SAC as *worse than no storage* on a full year. The horizon here is 24 known hours — an LP is exact. |
| Fine-tuning an extractor (ORLM/LLMOPT-style) | The guide forbids long training during evaluation, and there is no labelled corpus for these six directive types. |
| Retrieval / vector DB over the rules | Six directive types and one page of semantics. It all fits in the prompt. |
| Demand or solar forecasting | The 24 hours are given. Forecasting is out of scope. |
| Multi-agent debate at request time | Every extra turn is latency against a p95 ≤5 s target for 3 points. Ensemble sampling in **one** batched call gets the same disagreement signal for one round-trip. |
