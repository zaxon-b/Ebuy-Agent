# Canonical Eval v4 contract

The phase 0 contract freezes five non-compensating core metrics:

1. `task_success`: the case contract and every hard gate pass.
2. `final_state_accuracy`: all declared SQLite state assertions pass; read-only cases use N/A.
3. `tool_correctness`: valid tool path, arguments, forbidden tools and ordering are checked separately.
4. `policy_compliance`: every named deterministic policy predicate passes; one violation blocks task success. Cases with no applicable predicate use N/A.
5. `faithfulness`: `supported=1`, `unverifiable=0.5`, `contradicted=0`, `unsupported=0`.

`answer_quality`, `process_soundness`, token, latency and call counts are diagnostics only. There is no weighted overall score. Canonical cases are static or deterministic FSM cases; runtime LLM simulation is kept for the later Exploratory track and never contributes to the Canonical score.

Without the Faithfulness Judge, both `faithfulness` and `task_success` are incomplete (`N/A`) instead of automatically passing. An `unverifiable` verdict can pass only when the response honestly abstains and the matching policy predicate also passes.

`tool_correctness` reports the unweighted mean of applicable tool F1, argument accuracy, forbidden-tool pass and order pass. Case success still requires every applicable submetric to pass (`tool_correctness == 1.0`).
