# Teach the WellSenseIQ assistant without retraining the model

Keep the knowledge in WellSenseIQ and supply it at question time. Switching from
`qwen3:0.6b` to another model supported by the configured Ollama endpoint does
not require rebuilding the library, changing the database, or fine-tuning.
Model quality still varies: prefer a larger model for complex synthesis if the
small model struggles. Exact figures and rule-based checks do not depend on it.

| What you want the assistant to know | Where to maintain it |
| --- | --- |
| Product steps, calculations, codes, caution rules | The shipped Assistant memory and Operations guide. Update them alongside product changes. |
| A workspace-specific rule, checklist, or approved process | **Assistant → Memory**. An `assistant:manage` user can add or revise a note, set keywords and a matching screen, and set a required capability if the note is restricted. |
| Drilling, completion, or well-costing manuals and training material | Publish a workspace PDF reference index using the steps below. |
| The two supplied drilling engineering books (Rabia; Baker Hughes INTEQ) | Shipped inside the product: `backend/app/domain/operations/study_knowledge.py`. No indexing, no operator step — see below. |
| A live total, rate, daily report, depth, budget, or suspected entry error | Ask for the record, well, scope, or item by name. Existing permission-checked searches and calculations supply the evidence. Unsupported queries should be treated as unverified, not as zero. |

The model does not receive database credentials, execute SQL, approve reports,
or apply corrections. AI can explain results and suggest checks, but suspected
mistakes require human review. The assistant displays verified workspace results
separately from model commentary when a live answer is available. The daily
brief and report drafting controls use saved report evidence, not PDFs; a
reference must never be mistaken for an event, an HSE outcome, an approved
programme, or a value from the cost ledger.

## The supplied study books (shipped, no operator step)

Two references are part of the product rather than a workspace upload:

* H. Rabia, *Well Engineering & Construction* — pressure and the dc exponent,
  formation integrity and fracture gradient, kick tolerance, casing properties
  and design, wellbore stability, hole problems, fishing, horizontal and
  multilateral wells, HPHT, rig components, well costing.
* Baker Hughes INTEQ, *Drilling Engineering Workbook* (P/N 80270H Rev. B) —
  fluids and material balance, hydraulics and bit optimisation, casing and
  cementing, bit technology, drillstring and buoyancy, directional drilling,
  stuck pipe, well control, cost-per-foot.

`study_knowledge.py` stores, for each subject, **the derivation** (formula,
symbol definitions, the decision it informs), **printed ranges** where the book
states them, and **the page reference**. It does not store the books' prose:
the wording is ours, the arithmetic and the page are theirs. That keeps the
knowledge attributable and avoids reproducing copyrighted text.

The same entries feed three consumers, which is why an answer cannot drift
between them:

1. **The guide without AI** — `guide._study_answer()` answers a matching
   question with the formula, the symbols, what it applies to, the checks and
   the citation. No model is consulted.
2. **The offline AI prompt** — `study_context()` adds the matching derivation to
   the Ollama system prompt for guide answers, report extraction and the
   performance analyst, so a small model reasons with the arithmetic instead of
   recalling a rule of thumb.
3. **The reference library on `/operations/guide`** — `GET /operations/guide/study`
   lists every entry by subject, searchable, with its citation and an “Ask about
   this” jump into the ask box.

A value that depends on the well (a casing grade, a fracture gradient, a safe
mud weight) is never asserted. The entry says what must be measured and which
test measures it. When a printed value is offered, both the page and the range
are given.

## Add PDFs (server operator)

1. Put approved, text-searchable PDFs into a private folder, for example
   `ai-reference-pdfs/`. OCR scanned pages first. Only add documents that everyone
   with **Assistant read** in this workspace is authorized to see. Do not add
   confidential well records, credentials, or documents that need different
   per-document permissions. Relevant excerpts are sent to the configured LAN
   model when a user opts in to AI in Assistant or Well Operations → Ask & guide.
2. Get the target organization's **UUID** (not its slug) from the deployed
   database. For local Compose, the server operator can use:

   ```bash
   docker compose exec db psql -U postgres -d wellcosting -c 'SELECT slug, id FROM organizations;'
   ```

3. Build the index on a machine with the backend dependencies installed. From
   the repository root, for example:

   ```bash
   cd backend
   ../.venv/bin/python -m app.services.ai_knowledge \
     --workspace-id YOUR-WORKSPACE-UUID \
     --pdf-dir ../ai-reference-pdfs \
     --output-root ../ai-knowledge
   cd ..
   ```

   If you only use Docker, build the API image and index with that image instead:

   ```bash
   mkdir -p ai-knowledge
   docker compose build api
   docker compose run --rm --no-deps --user "$(id -u):$(id -g)" \
     --entrypoint python \
     -v "$PWD/ai-reference-pdfs:/app/reference-source:ro" \
     -v "$PWD/ai-knowledge:/app/reference-output" api \
     -m app.services.ai_knowledge --workspace-id YOUR-WORKSPACE-UUID \
     --pdf-dir /app/reference-source --output-root /app/reference-output
   ```

4. For a native API, set `AI_KNOWLEDGE_DIRECTORY` to the absolute path of the
   **output root** and restart the API. For Compose with LAN Ollama, add the
   optional read-only index mount (default host path `./ai-knowledge`):

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.ollama.yml \
     -f docker-compose.ai-knowledge.yml up -d --build
   ```

   The API looks only under the current workspace UUID. It does not ingest the
   original PDFs on startup or on user requests. It retrieves up to two relevant
   excerpts at a time and lists their PDF file names and physical page numbers
   in the answer. Lexical search works best with specific terms; include the
   exact acronym or phrase from the manual when a broad question misses.

5. Enable AI in either guide and ask a question that mentions a distinctive
   term from your PDFs. Check the listed pages and compare the answer against
   the source. Also ask for a known live value and verify that the answer shows
   the unchanged workspace result.

To update or remove documents, change the source folder and rerun the index
command for that workspace. Publication replaces the index atomically and the
API picks it up without a restart. To unpublish everything, remove that
workspace's `reference-index.json`. The index command reports blank/image pages
it skips. Files must be unencrypted; limits are 40 MiB per PDF, 2,400 pages per
workspace index, and 8 MiB for the published index. Source PDFs and derived
indexes are private deployment artifacts, not database backups; retain and
protect them separately. Missing/unreadable indexes leave the ordinary guide
available.

## Configure Qwen3 0.6B

On the Ollama server, run `ollama pull qwen3:0.6b`. In the WellSenseIQ API `.env`,
set `OLLAMA_ENABLED=true`, `OLLAMA_MODEL=qwen3:0.6b`, `OLLAMA_THINK=false`, and the
correct `OLLAMA_BASE_URL`. Prefer the native `/api/chat` endpoint so the server
can disable thinking directly. Restart or recreate the API after changing its
environment, then use **Check connection**. Other configured models continue to
use the same knowledge library. See [LAN Ollama setup](ollama-ai.md).
