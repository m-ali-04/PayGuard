# PayGuard

## Project Overview
Prototypes for a finance client: (1) real-time fraud detection, (2) complaint triage.
Treat the provided data as if it belongs to the client. See CONTEXT.md for full context.

## Scope & Complexity
- The top priority is what the client asked for directly. Note anything out of scope instead of dropping it silently.
- These are prototypes of enterprise solutions: balance effort against results.
- Complexity must match the results. Don't add complexity without a proven gain.
- Practical, real-world performance beats leaderboard gains: no extensive hyperparameter tuning or ensembling done just to raise scores.
- Latency must be sufficient, but it never blocks an approach. Reduce it with the right tooling, not by compromising the model.
- Don't assume operating conditions (transaction volume, traffic type, alert/review capacity); raise them with the owner before using them.

## Collaboration Rules
- The project owner (solutions architect) makes every decision. Claude recommends options and doesn't decide alone.
- Review all code with the owner before finalising it. Flag code that introduces a new format or a new kind of code for the project.

## Planning Approach
Use this alongside standard planning practice. It's a guideline, not a replacement.
- Flag where more context or research is needed (for example, industry practices).
- Where it makes sense, break the problem into components, each with:
  - a clear scope and a workflow the team understands
  - a project-impact subsection on how decisions inside it affect the whole project
- Compare options by how the overall strategy would work under each choice, not by calling one better or worse.
- Scale the depth to how complex or important the decision is.

## Reproducibility & Documentation
- The project must run from a clean environment. Whenever a step adds a dependency, data step or command, update the dependency file and the setup instructions in the same change.
- Environment: `uv` + `pyproject.toml` + `uv.lock`, Python 3.12.
- Keep README.md current: setup, approach, results, and what was cut and why (or why something extra was added). Update it when a strategy decision is made, not at the end.

## AI Usage Tracking
- Keep `AI_USAGE.md` up to date: which AI tools were used, what for, and roughly what share of the code each produced.
- Code-share figures are estimated per component (see the method in `AI_USAGE.md`).
- Update it whenever AI-assisted work lands, and flag the update to the owner.

## Code Quality
- Keep code concise: no speculative abstractions, unused options, or "just in case" layers. Add complexity only when a current need justifies it.
- Clever solutions are welcome, but flag them for the owner's review before finalising. Code should be efficient *and* readable; optimise hot paths deliberately, not everywhere.
- One responsibility per function/module; small, well-named units over long ones.
- Training and serving share one feature/preprocessing code path; never reimplement a transformation for inference. A parity test checks served scores against offline scores.
- No dead code, commented-out blocks, or duplicated logic — extract shared logic once it repeats.
- Comments explain *why*, not *what*; the code itself should make the *what* obvious.
- Use the language's and framework's idiomatic patterns and standard library before adding dependencies. New dependencies are a decision for the owner.
- Handle errors explicitly at boundaries (I/O, external services, user input); don't scatter defensive checks internally.
- Write tests for meaningful behaviour, not to hit a coverage number.

## Git Workflow
- `main` always works. Each step happens on a short-lived branch with conventional commits; open a PR that explains what changed, why, how to verify it, and any AI_USAGE update.
- Run a code review on each PR and post the findings as comments; fix real problems or explain why not.
- The owner reviews and merges. Never merge yourself or push directly to `main`.
