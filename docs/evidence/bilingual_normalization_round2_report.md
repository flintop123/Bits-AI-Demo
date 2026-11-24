# Bilingual Normalization — Phase II Round-2 Evidence

**Project:** AgriAgent, CS F407 Artificial Intelligence, Group 17
**Evidence date:** 15 November 2026
**Branch:** `anuj/agentic-bilingual-normalization`
**Scope isolation:** No change was made to `agent.py`, `run_extractor.py` or Rishi's ReAct orchestration layer.

## 1. Outcome

The faculty feedback suggested that Hindi/English conversion was lookup-only. Repository inspection established that the prior implementation was already hybrid: exact catalogue matching, reviewed aliases, market-name transliteration and local MarianMT translation were present. The Round-2 change made the model path explicit, auditable and safer.

The resulting workflow now provides:

1. exact official-catalogue matching;
2. version-controlled reviewed bilingual aliases;
3. non-semantic transliteration for unknown market proper names;
4. local MarianMT translation for unresolved terms;
5. local Qwen contextual fallback after Marian rejection;
6. independent validation attempts and explicit rejection evidence;
7. human-reviewed approval through YAML when automatic validators disagree;
8. MongoDB history preserving the rejected model path after approval.

The official source value remains the database identity and filter value. A generated label never silently replaces it.

## 2. Implementation commits

| Commit | Change |
|---|---|
| `66eb4fb` | Add auditable bilingual model normalization |
| `adcf1c9` | Reject unsafe bilingual display translations |
| `54bbf5a` | Add independently validated Qwen translation fallback |
| `114ef40` | Add reviewed bilingual label approval workflow |

## 3. Models and execution

| Purpose | Model | Runtime | Remote API |
|---|---|---|---|
| Hindi→English neural translation | `Helsinki-NLP/opus-mt-hi-en` | Local Transformers / MarianMT | No |
| English→Hindi neural translation | `Helsinki-NLP/opus-mt-en-hi` | Local Transformers / MarianMT | No |
| Context-aware agricultural fallback | `qwen3:4b` | Local Ollama | No |
| Multilingual similarity experiment | `bge-m3` | Local Ollama | No |

Model identity, language direction, execution mode, validation status, proposed label, round-trip candidate and confidence basis are stored as structured evidence.

## 4. Live findings and corrections

### 4.1 Horse gram

The live MarianMT test produced an incorrect English label:

```text
कुलथी → Total
```

The incorrect label was not written to MongoDB. The standard agricultural mapping `कुलथी → Horse gram` was added to the reviewed YAML catalogue. The active Mongo label uses method `reviewed_bilingual_alias` while retaining the official value `कुलथी`.

### 4.2 Turmeric

For `हल्दी`, direct Marian validation failed. Qwen then correctly proposed:

```text
हल्दी → turmeric
```

The independent Marian reverse model produced `गोथिक`, so automatic validation remained inconclusive and the Qwen proposal was rejected from automatic use. The rejection was stored with:

- Qwen model `qwen3:4b`;
- proposed label `turmeric`;
- primary status `rejected_round_trip_mismatch`;
- fallback status `rejected_independent_round_trip_mismatch`;
- round-trip candidate `गोथिक`;
- unmodified official value `हल्दी`.

The proposal was exported to a pending review queue and then approved in the version-controlled YAML as `हल्दी → Turmeric`. Cache policy version 6 activated the reviewed label. The earlier policy-5 model evidence remains in MongoDB `translation_history`.

## 5. Why no embedding threshold was used

Raw single-term `bge-m3` similarity did not reliably separate correct and incorrect pairs:

| Hindi term | Candidate | Score | Expected relation |
|---|---|---:|---|
| हल्दी | turmeric | 0.4427 | Correct |
| हल्दी | Total | 0.4378 | Incorrect |
| कुलथी | Horse gram | 0.3141 | Correct |
| कुलथी | Total | 0.5379 | Incorrect |
| आलू | Potato | 0.5851 | Correct |
| आलू | Onion | 0.5593 | Incorrect |
| गेहूं | Wheat | 0.7303 | Correct |
| गेहूं | Rice | 0.6560 | Incorrect |

Agricultural sentence context improved some pairs but still failed to create a universal boundary:

| Contextual pair | Score |
|---|---:|
| हल्दी / turmeric | 0.6744 |
| हल्दी / Total | 0.4440 |
| कुलथी / Horse gram | 0.5983 |
| कुलथी / Total | 0.4938 |
| आलू / Potato | 0.7338 |
| आलू / Onion | 0.7347 |
| गेहूं / Wheat | 0.7807 |
| गेहूं / Rice | 0.7589 |

The incorrect `आलू / Onion` pair scored slightly higher than the correct `आलू / Potato` pair. Introducing a fixed threshold would therefore have created false approvals. The system records these calibration findings and uses reviewed approval instead.

## 6. Tool contract and safety boundaries

`CatalogTranslationAgent` exposes strict Pydantic-derived input and output JSON schemas. Its input includes the official value, entity type and language direction. Its output separates proposed and accepted labels, round-trip candidate, decision and structured evidence. Unknown fields are rejected.

Safety rules include:

- official values are immutable presentation identities;
- Qwen output is treated as a proposal, not a database command;
- market proper names cannot use semantic LLM translation;
- failed validation retains the source-language label;
- confidence remains `null` with basis `not_calibrated` rather than presenting an invented percentage;
- rejected proposals are exported for review;
- only YAML entries marked `review_status: approved` are loaded;
- policy refreshes retain prior labels and evidence in `translation_history`.

## 7. Main files

| File | Responsibility |
|---|---|
| `services/local_translation_service.py` | MarianMT translation and model metadata |
| `services/catalog_translation_agent.py` | Strict Qwen proposal and validation contract |
| `services/mandi_term_normalizer.py` | Hybrid resolution, rejection and reviewed-alias loading |
| `conn/mandi_catalog_labels.py` | Mongo cache, policy versioning and translation history |
| `sources/mandi_term_aliases.yaml` | Version-controlled reviewed approvals |
| `scripts/export_translation_review_queue.py` | Non-mutating rejected-proposal export |
| `docs/AGENTIC_BILINGUAL_NORMALIZATION.md` | Design and operational documentation |
| `tests/test_catalog_translation_agent.py` | Agent schema and validator tests |
| `tests/test_translation_review_queue.py` | Review-queue tests |

## 8. Mongo evidence

The active policy-6 records show:

| Official value | English label | Method | History |
|---|---|---|---|
| `कुलथी` | Horse gram | `reviewed_bilingual_alias` | No prior cached failure |
| `हल्दी` | Turmeric | `reviewed_bilingual_alias` | Policy-5 Marian and Qwen rejection preserved |

The original pending review record contained:

```json
{
  "entity_type": "crop",
  "official_value": "हल्दी",
  "target_language": "en",
  "proposed_label": "turmeric",
  "model_name": "qwen3:4b",
  "primary_validation_status": "rejected_round_trip_mismatch",
  "agentic_validation_status": "rejected_independent_round_trip_mismatch",
  "round_trip_candidate": "गोथिक",
  "review_status": "pending"
}
```

## 9. Verification

| Check | Result |
|---|---:|
| Focused bilingual tests | 31/31 passed |
| Full repository regression suite | 231/231 passed |
| `pip check` | No broken requirements |
| `git diff --check` | Passed |

The full suite prints an intentional missing-PDF failure trace from a negative test. The suite ends with `OK` and process exit code 0.

Run the focused suite:

```cmd
python -m unittest tests.test_local_translation_service tests.test_catalog_translation_agent tests.test_mandi_term_normalizer tests.test_mandi_catalog_labels tests.test_translation_review_queue -v
```

Export pending proposals without modifying data:

```cmd
python scripts\export_translation_review_queue.py
```

## 10. Conclusion

The final system is not lookup-only and is not unconstrained generation. It combines local neural translation, local Qwen reasoning, deterministic identity preservation, explicit rejection, version-controlled human approval and permanent decision history. The live failures discovered during testing are retained as evidence rather than hidden.
