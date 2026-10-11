# Knowledge retrieval (Phase 4)

How agents and the customer chatbot find grounded answers in bank documents, and how we make sure each
caller only sees what they are cleared to see.

## Corpus

| Source | Document | Sensitivity |
|---|---|---|
| `data/knowledge_base/nexabank_knowledge_base.md` | NB-KB-001, the NexaBank knowledge base (converted from the original `.docx` in `docs/source/`) | Public, except sections 13, 17, 18, 19 (internal) |
| `data/policies/NB-POL-FRAUD-001...` | Fraud detection and response (thresholds, indicators) | **Restricted** |
| `data/policies/NB-POL-AML-001...` | KYC completeness and AML escalation | **Restricted** |
| `data/policies/NB-POL-AUTH-001...` | Action authorization matrix | Internal |

Every document starts with front matter holding the metadata fields from KB section 19.2
(`document_id`, `version`, `effective_date`, `status`, `access_level`, `product`, `jurisdiction`...)
plus `sensitivity`. A document can raise the sensitivity of parts of itself with
`section_sensitivity: 13=internal, 17=internal`; the most specific section wins.

## Pipeline

```
Markdown + front matter -> parse into numbered sections -> chunk -> attach metadata -> resolve versions
        -> one BM25 index per clearance level -> search(query, clearance) -> ranked, cited passages
```

**Chunking rules** (so each chunk answers one kind of question): a FAQ question and its answer is one
chunk; tables stay whole unless long, then split by rows with the header repeated; short lines and
paragraphs are packed up to 160 words; every chunk carries its heading path (also indexed) and a stable
id `DOC@version:section:n`. This produces 98 chunks from the four documents.

**Versions** (KB 19.1, 19.3): if two active versions of a document exist, the older one is marked
`superseded` and is searchable only when a caller explicitly asks for history, which only employee
sessions may do.

**Search**: BM25 (pure Python, no model download, identical on every machine) over heading path plus
body, with light stemming and a synonym list (KB section 18 plus two project additions, labelled in
`synonyms.json`). Ties are broken by chunk id, so results are deterministic.

## Access control

Two independent limits; the **stricter** applies:

1. **Role**: the highest sensitivity a role may ever read (`config/rag_access.py`). Roles not listed have
   no clearance.
2. **Session channel**: a customer-facing session can read nothing above Public, whichever agent serves it.

The channel is set by orchestration on the `ToolCall` and **defaults to customer**, so forgetting to set it
fails closed. The model controls only the query text, which cannot widen access.

**Filtering happens before ranking.** There is one index per clearance level, built only from the chunks
that level may see. A customer query runs against an index in which internal and restricted material does
not exist, so it cannot be ranked, scored or counted. There is no "N results hidden" signal and no
side channel through scoring.

Retrieved passages are marked `content_is_reference_data` and the audit log records which document
versions were consulted (policy references), never the query text itself.

## Evaluation

`data/knowledge_base/retrieval_eval.json` holds 40 labelled questions (30 customer-style, 10 employee-style);
a hit counts if it comes from any listed correct section. Run it with `nexa.rag.evaluation.evaluate`.

| Metric | Score |
|---|---|
| Questions with a correct section in the top 5 | 40 / 40 |
| Recall@1 | 0.85 |
| Recall@3 | 0.925 |
| Mean reciprocal rank | 0.90 |

**Read these numbers with care.** I wrote the questions after reading the corpus, the set is small, and two
synonym groups ("abroad", "failed logins") were added after the first run showed those two questions
missing. Real customers will phrase things differently, so expect lower scores on unseen questions.

## Limits and next steps

- Lexical search cannot bridge wording the synonym list does not cover. Dense or hybrid retrieval can be
  added behind the same `KnowledgeSearch` interface and compared on the same questions.
- Documents are curated and trusted, but passages are still handed to agents as data, never instructions.
- Re-ingestion is manual: change a document, bump its version, reload.
- Sensitivity labels are assigned by people. A mislabelled section would leak; the tests check the labels
  we have, not the judgement behind them.
