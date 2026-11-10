# Phase II Evaluation Set

## Scope and separation

The evaluation set contains 40 checked cases: ten for each implemented agent. Cases and reference outputs are stored separately under `eval/cases` and `eval/reference`. These cases were not used to train the production Qwen model. The optional LoRA experiment uses `eval/training/intent_router_train.json`; `eval/run_adapter_experiment.py` hashes normalized questions and stops if any held-out question occurs in that training set.

The existing seven-case AgentEvals suite remains an end-to-end and trajectory evaluation. The 40-case set adds the per-agent minimum required by the Phase II protocol.

## Normalization and field matching

- Text is normalized to Unicode NFC. Repeated whitespace is collapsed.
- English comparison is case-insensitive. Devanagari text is preserved.
- Financial years retain the `YYYY-YY` representation used by the source.
- Mandi dates use ISO `YYYY-MM-DD` and official source codes are retained as strings where leading zeroes may matter.
- Crop, location and period must identify the same source record before values are compared.
- Integers and codes require exact equality.
- Decimal values pass within one percent relative error after unit alignment.
- Units must match exactly. `tonne`, `quintal`, `kg_per_hectare`, `bale_170_kg` and `bale_180_kg` are distinct units.
- The database keeps official Hindi source labels. Reviewed English/Hindi aliases are presentation fields and do not replace source values.
- District and market codes are taken from the Bihar Krishi source. LGD-code alignment is recorded only where the official source supplies or a reviewed mapping establishes it; it is not guessed.

## Trajectory comparison

Tool selection and tool inputs use exact comparison. Multi-agent trajectories use unordered comparison only when independent source agents are intentionally run in parallel; single-agent cases use strict order. Retries are reported separately and are not hidden as expected calls.

## References

Crop references were checked against the committed DA&FW workbook and retain source-row locators. PDF references were checked against the identified source pages and the committed extraction evidence. Historical mandi counts were checked against the official API run trace. QA references specify intent, output language, expected source and only the minimum facts needed for deterministic checking.

## Live and surprise evaluation

`python eval/run_eval.py` runs all 40 cases, writes case-level evidence and produces one metric row per agent and source group. `python eval/run_eval.py --skip-qa` is only a fast preflight and deliberately omits the ten model-dependent QA cases. The instructor's three surprise items are not included in this repository. Their answers and M5 result must be written during the live evaluation without changing code. The generic entry point is:

```powershell
python run.py --input <file>
```

## Adapter comparison

`python eval/run_adapter_experiment.py` performs a genuine PEFT LoRA experiment on the QA agent's intent-routing decision. It compares the same `google/flan-t5-small` checkpoint before and after the adapter on the ten held-out QA cases and writes `eval/adapter_comparison.csv`. This experiment is kept distinct from production: deployed answer generation continues to use `qwen3:4b` through Ollama. The comparison is evidence about what adaptation adds to one agent decision, not a claim that Qwen itself was fine-tuned.
