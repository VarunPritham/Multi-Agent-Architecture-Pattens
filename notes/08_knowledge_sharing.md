# Knowledge Sharing
## Shared Epistemic Memory + Collective Intelligence

---

## What Problem Does This Solve?

In a naive multi-agent system, every agent starts from zero. Agent Alpha discovers how to fix Error 503 on ProWidget X. Twenty minutes later Agent Beta encounters the same error and investigates from scratch — duplicating effort, wasting time, and possibly reaching a different (worse) conclusion.

The Knowledge Sharing pattern fixes this with one insight: **discoveries should outlive the agent that made them.**

When Alpha writes its solution to a shared knowledge base, Beta finds it via semantic search. The system gets smarter with every resolved query — not just within one agent's memory, but across all agents, across time.

---

## The Knowledge Base as Shared Epistemic Memory

The knowledge base is not a cache. It is the system's collective memory — a record of what the agent collective has learned, who learned it, how confident they were, and how well the knowledge has held up under peer review.

Every entry has:
- **Provenance** — which agent wrote it, when
- **Confidence** — the author's initial certainty (0–100%)
- **Trust signals** — peer ratings (1–5★) and use count
- **Status** — ACTIVE or DEPRECATED (never deleted)

```
KnowledgeEntry
  entry_id:          8-char hex (UUID4)
  problem_description: the query that triggered the discovery
  solution_steps:    the answer — steps, workaround, explanation
  agent_id:          who wrote it
  confidence:        0.0–1.0 (author's initial certainty)
  tags:              ["hardware", "connectivity"] — domain labels
  created_at:        ISO timestamp
  use_count:         how many times retrieved and applied
  rating_sum:        sum of peer ratings received
  rating_count:      number of peer ratings
  deprecated:        False (active) or True (governance action)
```

The `trust_score` property blends all signals into a single 0–1 number used to rank retrieval results:

```python
@property
def trust_score(self) -> float:
    avg_rating = (self.rating_sum / self.rating_count) if self.rating_count else 2.5
    rating_component = avg_rating / 5.0
    use_component = min(1.0, self.use_count / 10)
    return 0.50 * self.confidence + 0.35 * rating_component + 0.15 * use_component
```

A brand-new entry from a confident author starts at ~50% trust. That number rises as peers rate it well and use it, or falls as peers rate it poorly.

---

## Semantic Search Without External APIs

The knowledge base must answer the question: "Do we already know something relevant to this query?"

Exact-match lookup fails — customers never phrase the same problem identically. The system needs semantic retrieval.

The implementation uses **TF-IDF cosine similarity** — built from the standard library, no external embeddings or vector databases required:

```python
def _tfidf_vector(self, text: str) -> dict[str, float]:
    tokens = re.findall(r'[a-z]+', text.lower())
    tf = Counter(tokens)
    total = sum(tf.values()) or 1
    N = len(self._entries) + 1
    vec = {}
    for term, count in tf.items():
        df = sum(1 for e in self._entries.values()
                 if term in e.problem_description.lower())
        idf = math.log((N + 1) / (df + 1)) + 1
        vec[term] = (count / total) * idf
    return vec

def _similarity(self, a: dict, b: dict) -> float:
    dot    = sum(a.get(t, 0) * b.get(t, 0) for t in a)
    mag_a  = math.sqrt(sum(v**2 for v in a.values())) or 1
    mag_b  = math.sqrt(sum(v**2 for v in b.values())) or 1
    return dot / (mag_a * mag_b)
```

**Why TF-IDF works here:**
- Domain queries ("Error 503", "ProWidget X", "dropping WiFi") have strong vocabulary signal
- TF-IDF naturally down-weights stop words ("the", "a", "is") and up-weights rare domain terms
- Cosine similarity ignores length — a 3-word query matches a 50-word description if they share key terms

**Limitations vs embedding models:**
- Cannot handle synonyms ("fix" vs "resolve") as well
- No cross-lingual support
- Similarity degrades for very short queries

For production use with open-ended natural language, swap `_tfidf_vector` for an embedding API call (e.g. `text-embedding-3-small`) while keeping the rest of the architecture identical.

---

## The Retrieval-Before-Discovery Loop

Every agent follows the same protocol:

```python
def handle(self, query: str) -> str:
    hits = self.kb.semantic_search(query)

    if hits:                                 # KB HIT
        best = hits[0]
        self.kb.rate_entry(best.entry_id, self.agent_id, self._evaluate(best))
        return best.solution_steps

    solution = self._discover(query)         # KB MISS — do the work

    self.kb.add_entry(KnowledgeEntry(
        entry_id=uuid.uuid4().hex[:8],
        problem_description=query,
        solution_steps=solution,
        agent_id=self.agent_id,
        confidence=0.82,
        tags=self._infer_tags(query),
    ))
    return solution
```

**KB HIT path**: find existing knowledge → rate it (feedback signal) → return immediately
**KB MISS path**: do full investigation → write discovery to KB → return

The critical invariant: **every novel discovery is written to KB**. An agent that solves a problem and doesn't share it is a waste.

---

## Trust Accumulation Over Time

The system improves without any manual curation. The mechanism:

1. **Alpha** discovers Error 503 fix → writes with confidence 82% → trust_score ≈ 0.66
2. **Beta** encounters similar error → KB hit → rates Alpha's entry 5★ → trust_score rises to 0.72
3. **Gamma** encounters same error → KB hit → rates 4★ → trust_score rises to 0.75
4. **Delta** encounters same error → KB hit with higher similarity × trust product → Alpha's entry is returned first

By step 4, Alpha's entry is the dominant answer for that problem class — not because Alpha is privileged, but because the peer rating process surfaced it as reliable.

Contrast this with a rogue entry:
1. **Rogue** writes "any error → factory reset" with low confidence 30% → trust_score ≈ 0.32
2. **Alpha** rates it 1★ (bad advice) → trust_score drops to 0.19
3. **Beta** rates it 2★ → trust_score drops further
4. **GovernanceAgent** audits: avg_rating = 1.5, rating_count = 2 → deprecates

The bad answer is removed from search results without any human intervention.

---

## GovernanceAgent — Knowledge Quality Control

The GovernanceAgent is a specialised agent whose only job is auditing the knowledge base. It never handles customer queries.

```python
class GovernanceAgent:
    def run_audit(self):
        for entry in kb.active_entries():
            if entry.rating_count >= MIN_REVIEWS and entry.avg_rating < DEPRECATION_THRESHOLD:
                kb.deprecate_entry(entry.entry_id, "GovernanceAgent",
                    f"Low avg rating ({entry.avg_rating:.1f}/5) after {entry.rating_count} reviews")
        self._check_duplicates()

    def _check_duplicates(self, threshold=0.85):
        entries = kb.active_entries()
        for i, a in enumerate(entries):
            for b in entries[i+1:]:
                sim = kb._similarity(kb._tfidf_vector(a.problem_description),
                                     kb._tfidf_vector(b.problem_description))
                if sim > threshold:
                    log(f"Potential duplicate: [{a.entry_id}] ↔ [{b.entry_id}] (sim={sim:.2f})")
```

**Governance decisions:**
- `avg_rating < 2.0` after `≥ 2` reviews → DEPRECATED
- Similarity > 85% between two active entries → flagged for consolidation (human or automated merge)

**Why deprecated ≠ deleted:**
- Audit trail: you can reconstruct what the KB believed at any point in time
- Rollback: a wrongly deprecated entry can be re-activated
- Analysis: studying deprecated entries reveals where agents go wrong

---

## Collective Intelligence Metrics

After any run, the system can report:

```
total_entries        7     # all-time writes
active_entries       6     # currently searchable
deprecated_entries   1     # removed by governance
contributing_agents  5     # unique agent_ids
cache_hits           1     # queries resolved from KB
hit_rate            14%    # cache_hits / total_reads
```

The `hit_rate` is the system's primary efficiency metric. In a new deployment it starts near 0%. As the KB fills with high-quality entries covering common cases, it climbs. A mature support system might hit 60–80% — meaning 6 of every 10 queries are resolved without any LLM call.

---

## Comparison: Knowledge Sharing vs Other Patterns

| Pattern | Shared state | Adapts over time? | Scales how? |
|---|---|---|---|
| Supervisor | Checkpoint file (workflow state) | No | More workers |
| Swarm | TaskBoard (task status) | No | More pollers |
| Blackboard | Fact store (per-session) | No (cleared each session) | More specialists |
| **Knowledge Sharing** | **Persistent KB (cross-session)** | **Yes (trust accumulates)** | **More agents = more knowledge** |

The key distinction: Knowledge Sharing is the only pattern where **time is an asset**. The longer the system runs, the better it gets. The other patterns reset or complete.

---

## Pros and Cons

### Pros
- **Efficiency**: repeated problems resolved from KB — no LLM call needed
- **Collective improvement**: each agent makes all future agents smarter
- **Self-correcting**: bad knowledge is downgraded by peer ratings, removed by governance
- **Transparency**: full provenance and audit trail for every piece of knowledge
- **No external dependencies**: TF-IDF cosine similarity works without an embedding API

### Cons
- **Cold-start problem**: hit rate is zero until the KB has enough entries
- **Coverage gaps**: agents only know what has been encountered before; novel problems always miss
- **Trust drift**: if early peer ratings are biased, trust scores may not reflect actual quality
- **Duplicate accumulation**: similar-but-not-identical entries fragment the KB without governance
- **Staleness**: KB entries reflect past solutions; systems change, correct answers change

---

## When to Use

✅ Use when:
- Multiple agents handle similar or overlapping problem domains
- The same or similar queries recur frequently (support, diagnostics, recommendations)
- You want the system to improve over time without manual updates
- Agent effort is expensive (LLM calls, API lookups) and worth caching

❌ Avoid when:
- Problems are highly unique — low recurrence means low hit rate, KB overhead not worth it
- Correctness is safety-critical — peer ratings are not a substitute for expert validation
- The problem domain changes rapidly — KB entries go stale faster than trust can build
- You only have one agent — sharing requires multiple contributors

---

## Key Code Locations

| File | What it shows |
|------|---------------|
| `knowledge_sharing.py` | Full ProWidget customer support scenario — TF-IDF KB, 4 support agents, trust accumulation, rogue entry + governance deprecation, hit rate statistics |

---

## Real-World Equivalents

- **Stack Overflow**: developers post questions (KB miss), others provide solutions (write), community votes (rating), duplicate questions are closed (governance)
- **Medical literature**: a case report (write) gets cited (use_count), peer-reviewed (rating), retracted if wrong (deprecation)
- **Company wiki**: employee encounters novel problem → writes solution → colleagues find it via search → upvote if helpful → stale articles are archived
- **Recommendation engines**: user actions (writes + ratings) build a model that surfaces better answers for future users
