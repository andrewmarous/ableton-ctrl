# Ableton Production Wiki

This directory is a persistent knowledge base for Ableton Live how-to guides, tutorials, and electronic music production techniques. Read this file before you ingest sources, answer production questions, or maintain the wiki.

## Boundaries

- Treat `raw/` as immutable source material. Read files there; preserve their names and contents.
- Treat `wiki/` as agent-maintained material. Create and revise its Markdown pages as the evidence changes.
- Keep the wiki about using Ableton Live and producing electronic music. Extension implementation details belong elsewhere.
- Distinguish verified facts, source opinions, and your synthesis. Preserve uncertainty and disagreements.
- Give version-specific Ableton instructions an explicit Live version when the source provides one.

## Layout

- `raw/`: user-curated articles, transcripts, notes, images, and other source files.
- `raw/assets/`: local source attachments.
- `wiki/index.md`: categorized catalog of every generated wiki page.
- `wiki/log.md`: append-only activity history.
- `wiki/sources/`: one summary page per ingested source.
- `wiki/how-to/`: task-oriented Ableton procedures.
- `wiki/concepts/`: production and audio concepts.
- `wiki/techniques/`: reusable sound-design, arrangement, mixing, and workflow techniques.
- `wiki/devices/`: Ableton instruments, effects, MIDI tools, and related device notes.
- `wiki/genres/`: genre conventions and genre-specific guidance.
- `wiki/analyses/`: comparisons and synthesized answers worth preserving.

Create another category only when these categories cannot represent the material clearly.

## Page conventions

Use Obsidian-style `[[relative/path|label]]` links, with paths relative to `wiki/` and without `.md`. Use lowercase kebab-case filenames. Begin generated pages with:

```yaml
---
title: Page title
type: source | how-to | concept | technique | device | genre | analysis
created: YYYY-MM-DD
updated: YYYY-MM-DD
sources: []
tags: []
---
```

A source entry is a wiki link to a page in `sources/`. Cite claims inline with those links. Source pages must identify the raw file and include its title, creator when known, publication date when known, ingest date, summary, key claims, practical takeaways, and links to affected pages.

Write procedures with prerequisites, numbered steps, expected results, and troubleshooting. State whether advice is a rule, a useful default, or a creative option. Explain parameter choices instead of presenting unexplained settings as universal recipes.

Every generated page must be listed once in `wiki/index.md` with a one-line description. Add useful links in both directions when pages are closely related. Do not create links to pages that do not exist; add a clearly labeled data gap instead.

## Ingest

1. Read the new raw source and relevant existing wiki pages. Start with `wiki/index.md`.
2. Identify factual claims, procedures, creative advice, prerequisites, Ableton-version constraints, disagreements, and gaps.
3. Create or update one source page. Record the exact raw path.
4. Integrate the information into all affected how-to, concept, technique, device, genre, and analysis pages. Revise existing synthesis instead of duplicating it.
5. Add cross-references and update `wiki/index.md`.
6. Append `## [YYYY-MM-DD] ingest | Source title` to `wiki/log.md`, followed by the raw path and a concise list of changed pages.

Ingest is complete when each material claim has a source citation, affected existing pages reflect the new evidence, the index lists every generated page, and the log records the operation.

## Query

1. Read `wiki/index.md`, then the relevant wiki and source pages.
2. Answer from the wiki with links to supporting source pages. State gaps or conflicts.
3. When the answer adds durable synthesis, offer to save it in `wiki/analyses/` and connect it to related pages.
4. If saved, update the index and append `## [YYYY-MM-DD] query | Short topic` to the log.

## Lint

Check every generated page for missing index entries, orphaned pages, broken links, uncited claims, stale or conflicting guidance, duplicate coverage, missing Live-version qualifiers, and concepts that deserve their own page. Report data gaps separately from defects. Apply safe bookkeeping fixes, then append `## [YYYY-MM-DD] lint | Scope` to the log with findings and changed pages.
