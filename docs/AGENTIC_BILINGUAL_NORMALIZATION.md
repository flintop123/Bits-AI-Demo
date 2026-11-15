# Auditable bilingual catalogue normalization

## Purpose

Mandi source values remain the official database values used for identity and filtering. English and Hindi labels are presentation metadata. This prevents a translation model from silently changing a district, market, crop or variety identity.

The implementation is hybrid rather than lookup-only:

1. exact live-catalogue value;
2. reviewed bilingual alias;
3. proper-name transliteration for an unknown Hindi market;
4. local MarianMT translation for unresolved crop, district or variety labels;
5. live-catalogue validation before a translated query candidate is accepted;
6. unresolved fallback when validation fails.

No hosted translation API is used. The local neural models are:

- `Helsinki-NLP/opus-mt-hi-en` for Hindi to English;
- `Helsinki-NLP/opus-mt-en-hi` for English to Hindi.

## Safety boundary

The original official value is always retained. A generated translation may be used as a display label, but a translated query term is accepted only when it matches an existing live-catalogue value or reviewed alias. Unknown market proper names are transliterated rather than semantically translated.

## Stored evidence

Label policy version 4 stores an evidence block independently for the English and Hindi label. The block records:

- provider and model family;
- exact model name;
- source and target languages;
- local execution and whether a remote API was used;
- validation status;
- whether the official value was preserved;
- confidence and confidence basis.

MarianMT generation scores are not treated as calibrated semantic confidence. Consequently, `confidence` is recorded as `null` and `confidence_basis` as `not_calibrated`. This is more defensible than inventing a percentage.

## Validation statuses

| Status | Meaning |
|---|---|
| `not_required` | Source value already uses the requested display language |
| `accepted_reviewed_alias` | Human-reviewed bilingual alias used |
| `accepted_proper_name_transliteration` | Hindi market name romanized without semantic generation |
| `display_label_generated_offline` | Local MarianMT label generated while official value remains unchanged |
| `accepted_exact_catalog_match` | Model candidate exactly matched a live-catalogue value |
| `accepted_catalog_alias` | Model candidate matched a reviewed alias |
| `rejected_not_in_live_catalog` | Generated candidate was not accepted for filtering |
| `translation_failed` | Local model could not produce a result |
| `translation_unavailable` | Safe fallback retained the official label |

## Demonstration

Run the focused tests:

```cmd
python -m unittest tests.test_local_translation_service tests.test_mandi_term_normalizer tests.test_mandi_catalog_labels -v
```

The tests prove that model identity is exposed, original values remain unchanged, accepted candidates are catalogue-bound and unmatched model output is logged as rejected.

## Scope isolation

This change updates only the local translation service, term normalizer, label cache, their tests and this documentation. It does not modify `agent.py`, `run_extractor.py` or the existing ReAct orchestration layer.
