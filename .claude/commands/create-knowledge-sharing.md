Create a new Knowledge Sharing implementation for the following domain: $ARGUMENTS

Follow the Knowledge Sharing pattern exactly:

**Step 1 — Define KnowledgeEntry dataclass**
- Fields: `entry_id` (uuid4 hex), `problem_description`, `solution_steps`, `agent_id`, `confidence` (float 0–1), `tags` (list[str]), `created_at` (ISO timestamp)
- Trust signals: `use_count` (int), `rating_sum` (float), `rating_count` (int), `deprecated` (bool, default False)
- `trust_score` property: blend confidence + normalised rating average + use count signal
  - Formula: `0.5 * confidence + 0.35 * (avg_rating / 5.0 if rated else 0.5) + 0.15 * min(1.0, use_count / 10)`

**Step 2 — Build SharedKnowledgeBase**
- Internal store: `_entries: dict[str, KnowledgeEntry]`
- `_tfidf_vector(text) → dict[str, float]` — pure-Python TF-IDF, no external libraries
- `_similarity(a, b) → float` — cosine similarity between two TF-IDF dicts
- `add_entry(entry) → None` — write to store, print `[KB] ✍  Written by <agent>: <preview>`
- `semantic_search(query, threshold=0.1, top_k=3) → list[KnowledgeEntry]`
  - Score each ACTIVE entry: `similarity(query_vec, entry_vec) × entry.trust_score`
  - Return top_k above threshold, sorted descending
  - Increment `use_count` on hit
- `rate_entry(entry_id, agent_id, rating) → None` — update rating_sum + rating_count; print `[KB] ★  <agent> rated [<id>] → <r>/5`
- `deprecate_entry(entry_id, agent_id, reason) → None` — set `deprecated=True`; print `[KB] ⛔ <agent> deprecated [<id>]: <reason>`
- `stats() → dict` — return dict with: total_entries, active_entries, deprecated_entries, contributing_agents, total_writes, total_reads, cache_hits, hit_rate (%)

**Step 3 — Build worker agents (minimum 4, domain-specific)**
- One `WorkerAgent` base class with `handle(query: str) → str`
  1. `kb.semantic_search(query)` — check for existing knowledge
  2. KB HIT: log match + similarity score, rate entry, return existing solution
  3. KB MISS: call `_discover(query)` (LLM or mock), write new entry via `kb.add_entry()`, return solution
- Subclass for each domain specialist (e.g. HardwareAgent, NetworkAgent, SoftwareAgent, BillingAgent)
- Each subclass has domain-specific mock solutions appropriate to the use case
- LLM path: use Anthropic client with tool_use to get structured `{solution_steps, confidence, tags}`

**Step 4 — Build GovernanceAgent**
- `run_audit() → None`:
  - Scan all entries: deprecate those with `avg_rating < 2.0` after `min_reviews >= 2`
  - Call `_check_duplicates()` to flag near-identical pairs
  - Print audit summary
- `_check_duplicates(threshold=0.85) → list[tuple]`:
  - Compare all active entry pairs by similarity
  - Return pairs above threshold (potential duplicates)
  - Log warning for each flagged pair

**Step 5 — 4-phase demo**
- Phase 1: novel queries → all KB misses → KB grows; show `[KB] ✍  Written` messages
- Phase 2: similar/overlapping queries → some KB hits emerge; show `[KB HIT (score=X.XX)]`
- Phase 3: inject a low-quality rogue entry, have agents rate it poorly (1–2★), run `governance.run_audit()` → deprecation
- Phase 4: print full KB table + statistics block

**KB table format:**
```
──────────────────────────────────────────────────────────
KNOWLEDGE BASE (<N> entries)
──────────────────────────────────────────────────────────
✓ ACTIVE    [<id8>] <problem_description preview 65 chars>
By: <agent_id>    | conf=XX% | trust=XX% | uses=N | N.N★
⛔ DEPRECATED  [<id8>] <problem_description preview>
By: <agent_id>    | conf=XX% | trust=XX% | uses=N | N.N★
```

**Statistics block format:**
```
total_entries                N
active_entries               N
deprecated_entries           N
contributing_agents          N
total_writes                 N
total_reads                  N
cache_hits                   N
hit_rate                     N%
```

**Final summary line:**
```
Of N support queries, X were resolved using shared KB knowledge — zero re-investigation needed.
N agents contributed to a pool of M active solutions.
K low-quality entries deprecated by GovernanceAgent — KB integrity maintained.
```

**Plan DAG requirements for the demo:**
- Minimum 6 queries across 4 agents
- At least 1 KB hit in Phase 2 (similar enough problem to trigger retrieval)
- At least 1 rogue/low-quality entry introduced and deprecated in Phase 3
- At least 2 highly-rated entries that survive governance

Save the file to: /Users/varunpritham/Me and Claude/Multi Agent Architectures/knowledge_sharing_<domain>.py
