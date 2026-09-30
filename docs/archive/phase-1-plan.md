# V2 Phase 1: managed library implementation

Source of requirements: `Home_Manager_Architecture_Implementation_Spec.docx`, sections 1–3, 16–18, 21–23 and 26.

## Concrete change plan

1. Migration 007 adds explicit legacy-to-flat folder aliases and migrates active manual folder assignments. Append migration events; leave historical events, parsing JSON and organization runs unchanged. Historical evidence remains readable with legacy folder names.
2. Migration 008 adds per-document/version managed paths, organization intents and organization events. Existing external occurrences remain external. Inbox occurrences explicitly record their origin; their absent folder period uses 0 rather than an invented financial date.
3. Create the allow-listed `Library` directories. Generate filenames in trusted code from validated date/type and a conservative merchant label, plus document ID and content hash. Never use model paths or account identifiers in filenames. Copies are independent bytes, never hard links to immutable blobs.
4. Implement organization as durable intent → verified source/blob → atomic non-overwriting publication/move → database event. Retry pending intents at startup. Preserve edited files and report a conflict rather than replacing them. Keep old version copies and source provenance.
5. Add a separate flat Inbox scan mode using the existing bounded capture worker. Unclassified Inbox files stay in Inbox; external imports get Unfiled copies. Process existing capture gaps at startup. A successful saved analysis with supported type, identifying metadata and valid source citations can trigger filing; this is a narrow adapter pending the dedicated classifier in Phase 5. Manual folder choices take precedence.
6. Show flat folders, Inbox scanning, managed paths and organization reasons in the current library UI. Preserve explicit confirmation for logical Trash. No general visual redesign.
7. Test v6 migration/backup, external-source integrity, Inbox capture-before-move, filename confinement and collisions, modified managed files, partial failures/restart recovery, classification fallback, API validation, and the browser workflow.

## Phase boundary

Implementation delivered in the working tree: migrations 007–008, managed organization service, Inbox scan API/UI, validated-analysis filing adapter, and regression/acceptance tests. Operating details and current limitations are in [managed-library.md](managed-library.md).

Phase 1 retained the serialized worker; later phases are described in [v2-phases.md](v2-phases.md). No model confidence threshold is invented. Unknown or missing identifying metadata remains Inbox/Unfiled. Model-derived filing is convenience organization, not financial approval.
