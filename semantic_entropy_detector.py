#!/usr/bin/env python3
"""Semantic Entropy Fabrication Detector.

Local-Ollama implementation of semantic uncertainty: repeated sampling,
mutual-entailment clustering, Shannon entropy, lexical baseline, and an
explicitly experimental Forman-Ricci signal. Thresholds are arbitrary until
validated against labeled data. The self-test validates arithmetic only.
"""
from __future__ import annotations
import argparse, hashlib, json, math, sys, time, urllib.error, urllib.request
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple
import networkx as nx
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

OLLAMA_URL = "http://localhost:11434/api/generate"
ENTROPY_BANDS = [(0.30, "LOW — consistent semantic content, likely reliable"),
                 (1.00, "MEDIUM — some divergence, verify independently"),
                 (float("inf"), "HIGH — semantically inconsistent across samples, treat as unreliable/confabulated")]


def cluster_by_entailment(n: int, mutual_entails: List[Tuple[int, int]]) -> List[List[int]]:
    parent = list(range(n))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb: parent[ra] = rb
    for i, j in mutual_entails: union(i, j)
    groups: Dict[int, List[int]] = {}
    for i in range(n): groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def shannon_entropy_bits(cluster_sizes: List[int]) -> float:
    n = sum(cluster_sizes)
    return 0.0 if n == 0 else -sum((c/n) * math.log2(c/n) for c in cluster_sizes if c)


def lexical_entropy(samples: List[str]) -> Tuple[float, List[List[int]]]:
    groups: Dict[str, List[int]] = {}
    for i, sample in enumerate(" ".join(s.strip().lower().split()) for s in samples):
        groups.setdefault(sample, []).append(i)
    clusters = list(groups.values())
    return shannon_entropy_bits([len(c) for c in clusters]), clusters


def tfidf_similarity_matrix(samples: List[str]) -> np.ndarray:
    if len(samples) < 2: return np.zeros((len(samples), len(samples)))
    return cosine_similarity(TfidfVectorizer().fit_transform(samples))


def forman_ricci_weighted(similarity_matrix: np.ndarray, sim_threshold: float = 0.15) -> Dict[str, float]:
    G = nx.Graph(); G.add_nodes_from(range(similarity_matrix.shape[0]))
    for i in range(similarity_matrix.shape[0]):
        for j in range(i + 1, similarity_matrix.shape[0]):
            w = float(similarity_matrix[i, j])
            if w > sim_threshold: G.add_edge(i, j, weight=w)
    if not G.edges:
        return {"mean_curvature": float("nan"), "min_curvature": float("nan"), "max_curvature": float("nan"), "n_edges": 0}
    values = []
    for u, v, data in G.edges(data=True):
        w = data["weight"]
        incident = 0.0
        for nbr in G.neighbors(u):
            if nbr != v: incident += 1.0 / math.sqrt(w * G[u][nbr]["weight"])
        for nbr in G.neighbors(v):
            if nbr != u: incident += 1.0 / math.sqrt(w * G[v][nbr]["weight"])
        values.append(w * (2.0 / w - incident))
    return {"mean_curvature": float(np.mean(values)), "min_curvature": float(np.min(values)),
            "max_curvature": float(np.max(values)), "n_edges": len(values)}


def band_for_entropy(h: float) -> str:
    for cutoff, label in ENTROPY_BANDS:
        if h <= cutoff: return label
    return ENTROPY_BANDS[-1][1]


def ollama_generate(prompt: str, model: str, temperature: float = 0.9, timeout: int = 120) -> str:
    payload = {"model": model, "prompt": prompt, "stream": False, "options": {"temperature": temperature}}
    req = urllib.request.Request(OLLAMA_URL, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode()).get("response", "").strip()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Ollama at {OLLAMA_URL}: {exc}") from exc

JUDGE_TEMPLATE = """You are a strict semantic entailment judge. Decide whether two answers to the same question assert the SAME core fact. Ignore wording, verbosity, and formatting. Answer NO for contradiction, non-overlap, or refusal. Respond with exactly YES or NO.\n\nQuestion: {question}\nAnswer A: {a}\nAnswer B: {b}"""


def llm_judge_mutual_entailment(question: str, a: str, b: str, judge_model: str) -> bool:
    return ollama_generate(JUDGE_TEMPLATE.format(question=question, a=a, b=b), judge_model, 0.0).strip().upper().startswith("Y")


def build_entailment_pairs(question: str, samples: List[str], judge_model: str) -> List[Tuple[int, int]]:
    return [(i, j) for i in range(len(samples)) for j in range(i + 1, len(samples))
            if llm_judge_mutual_entailment(question, samples[i], samples[j], judge_model)]

@dataclass
class DetectionResult:
    question: str
    model: str
    judge_model: str
    n_samples: int
    samples: List[str]
    semantic_entropy_bits: float
    lexical_entropy_bits: float
    semantic_clusters: List[List[int]]
    lexical_clusters: List[List[int]]
    verdict: str
    forman_ricci: Dict[str, float]
    provenance_hash: str = ""
    timestamp: float = field(default_factory=time.time)
    previous_provenance_hash: Optional[str] = None

    def to_json(self) -> str: return json.dumps(asdict(self), indent=2)


def run_detection(question: str, model: str, n_samples: int = 10, temperature: float = 0.9,
                  judge_model: Optional[str] = None, previous_hash: Optional[str] = None) -> DetectionResult:
    judge_model = judge_model or model
    samples = [ollama_generate(question, model, temperature) for _ in range(n_samples)]
    pairs = build_entailment_pairs(question, samples, judge_model)
    sem_clusters = cluster_by_entailment(n_samples, pairs)
    sem_h = shannon_entropy_bits([len(c) for c in sem_clusters])
    lex_h, lex_clusters = lexical_entropy(samples)
    ricci = forman_ricci_weighted(tfidf_similarity_matrix(samples))
    result = DetectionResult(question, model, judge_model, n_samples, samples, sem_h, lex_h,
                             sem_clusters, lex_clusters, band_for_entropy(sem_h), ricci,
                             previous_provenance_hash=previous_hash)
    payload = json.dumps(asdict(result), sort_keys=True, default=str).encode()
    result.provenance_hash = hashlib.sha256(payload).hexdigest()
    return result


def selftest() -> None:
    consistent = ["The treaty ended the war in 1648.", "The war concluded in 1648.", "1648 marked the end of the war.", "It ended in 1648.", "The conflict finished in 1648."]
    pairs = [(i, j) for i in range(5) for j in range(i + 1, 5)]
    assert shannon_entropy_bits([len(c) for c in cluster_by_entailment(5, pairs)]) == 0.0
    assert lexical_entropy(consistent)[0] > 0.0
    assert abs(shannon_entropy_bits([1, 1, 1, 1, 1]) - math.log2(5)) < 1e-9
    ricci = forman_ricci_weighted(np.array([[1,.9,.9],[.9,1,.9],[.9,.9,1]]), 0.0)
    assert ricci["n_edges"] == 3
    print("ALL SELF-TESTS PASSED. Arithmetic/clustering validated; model/judge validity is not established.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--question"); ap.add_argument("--batch"); ap.add_argument("--model", default="llama3.1")
    ap.add_argument("--judge-model"); ap.add_argument("--n", type=int, default=10); ap.add_argument("--temperature", type=float, default=0.9)
    ap.add_argument("--log"); ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest: selftest(); return
    if not args.question and not args.batch: ap.error("provide --question, --batch, or --selftest")
    questions = ([args.question] if args.question else [])
    if args.batch:
        with open(args.batch) as fh: questions.extend(line.strip() for line in fh if line.strip())
    previous = None
    log = open(args.log, "a") if args.log else None
    try:
        for q in questions:
            result = run_detection(q, args.model, args.n, args.temperature, args.judge_model, previous)
            previous = result.provenance_hash
            print(f"Semantic entropy: {result.semantic_entropy_bits:.3f} bits | Lexical: {result.lexical_entropy_bits:.3f} bits")
            print(f"Verdict: {result.verdict}\nprovenance_hash: {result.provenance_hash}")
            if log: log.write(json.dumps(asdict(result), sort_keys=True) + "\n")
    finally:
        if log: log.close()

if __name__ == "__main__": main()
