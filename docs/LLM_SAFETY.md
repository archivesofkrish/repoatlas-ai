# LLM answer safety and data flow

RepoAtlas keeps repository retrieval and model generation as separate operations.

## Invocation and data flow

- `repoatlas ask` and `POST /v1/ask` are retrieval-only. They do not call a model.
- `repoatlas answer` and `POST /v1/answer` are explicit opt-in operations. They require the optional `llm` extra and an `OPENAI_API_KEY`.
- RepoAtlas captures a bounded source snapshot, retrieves the relevant excerpts, and applies its secret-redaction heuristics before constructing the provider request.
- The provider receives the question and the selected evidence records (file path, line range, file hash, retrieval reason, and a bounded excerpt). It does not receive the full repository snapshot.
- Each excerpt is limited to 2,400 characters. The answer request uses strict JSON-schema output, has a bounded output-token allowance, sets `store=False`, and supplies no model tools.
- The default model is `gpt-6.1-sol`. Operators may set `REPOATLAS_OPENAI_MODEL` to an approved compatible model.

Use the provider only after reviewing its current data controls and obtaining any organisational approval required for source-code disclosure. `store=False` is a request parameter; do not interpret it as a guarantee of zero retention across all provider systems or account configurations.

## Trust boundaries

Repository files, comments, docstrings, identifiers, and retrieved excerpts are untrusted data. They may contain malicious prompt-injection instructions. RepoAtlas places them in the user data payload, while the static provider instructions explicitly tell the model not to treat repository content as instructions. The model has no tools, no shell access, no network tools, and no ability to modify the repository.

## Claim and citation validation

The provider must return structured claim objects. Each claim must include one to five unique evidence IDs. RepoAtlas then:

1. Rejects any evidence ID not assigned to a retrieved record.
2. Checks that the cited path is relative, remains inside the repository, and is not a symlink.
3. Checks that the cited line range exists.
4. Recomputes the file SHA-256 and rejects the claim if the source changed during model generation.
5. Returns the validated citation next to the claim; claims cannot be rendered without these checks.

No-evidence retrieval skips the provider entirely. Provider errors, malformed JSON, malformed claims, unknown evidence IDs, and stale citations fail closed rather than returning an unverified answer.

## What this does not prove

A valid file hash proves that the cited file matches the captured source bytes. A valid line range proves that those lines exist. An allow-listed evidence ID proves that the model selected one of the supplied records. None of these guarantees that the text logically entails the generated statement.

RepoAtlas therefore reports provenance validation, not formal semantic verification. Model claims can still be incomplete, misleading, or wrong. Human review remains necessary before using an answer for security, production, compliance, or other consequential decisions.

Secret redaction is heuristic and can miss credentials. Never assume it removes all sensitive data. Review the snippets that RepoAtlas retrieves, and do not use provider-backed answering on code that your organisation has not approved for external processing.
