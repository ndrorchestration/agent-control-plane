# Semantic Entropy Fabrication Detector

A local-Ollama implementation of semantic uncertainty for detecting instability across repeated model answers.

## Status

**Experimental evaluation tool.** The offline self-test validates the arithmetic and clustering mechanics; it does not validate the LLM generator, entailment judge, thresholds, or verdicts against a human-labeled gold set.

## Signals

- Semantic entropy: primary published mechanism.
- Lexical entropy: exact-string baseline used to test whether semantic clustering adds information.
- Forman–Ricci curvature: experimental graph signal, reported separately and never fused into the verdict.
- SHA-256 provenance hash with optional previous-hash linkage for JSONL runs.

## Epistemic constraints

Entropy bands are arbitrary starting points and must be tuned against labeled data. N=10 is a noisy default. Same-family generator/judge bias is a known confound. Pairwise entailment clustering uses union-find and therefore assumes transitivity; intransitive judge decisions can inflate semantic entropy. Treat the output as a ranking signal across many questions, not a certified truth verdict for an individual answer.

## Quickstart

```bash
pip install -r requirements.txt
python semantic_entropy_detector.py --selftest
```

Real use requires a local Ollama server and a pulled model:

```bash
ollama pull llama3.1
python semantic_entropy_detector.py --question "What year did the Treaty of Westphalia end the Thirty Years' War?" --model llama3.1
```

Batch provenance logging:

```bash
python semantic_entropy_detector.py --batch questions.txt --model llama3.1 --log run_log.jsonl
```

## Provenance terminology

The detector stores a current result hash and can carry the previous result hash into the next result. This is a hash-linked provenance sequence; it should not be described as tamper-evident ledger infrastructure without an external append-only storage/control.
