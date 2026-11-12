# MEMORY.md import profile

Use this profile when notes are prose bullets with bold labels and inline dates
or amounts, rather than explicitly tagged `fact:`/`debt:` rows:

```bash
git pull --ff-only
mkdir -p local
umask 077
python3 memory.py prepare-import --profile memory-md /actual/path/to/MEMORY.md \
  > local/new-preview.import.jsonl
```

Review that file before importing. Every object has `approved: false`, and every
item has `confidence: reported`. The command does not open the database or edit
notes. Do not overwrite an already reviewed import file when generating a new
preview. The original `tagged` profile remains the default.

## Section patterns

Recognized ATX Markdown headings (`#` through `######`) are case-insensitive.
Bold heading text, a trailing colon, and closing `#` marks are supported. Heading
names match the following explicit list; there is no fuzzy classification.

| Heading | Candidate kind |
| --- | --- |
| Commitment, Commitments, Debt, Debts | `commitment` |
| Fact, Facts | `fact` |
| Person, People, People index | `person` |
| Goal, Goals | `goal` |
| Question, Questions, Open questions | `question` |

An unknown subsection inherits its nearest recognized ancestor. A sibling or
higher-level heading ends the previous section's scope. Context resets for each
file. Bullets under unknown sections are skipped unless a question phrase, an
explicit tag, or a checkbox supplies a recognized pattern.

Classification precedence is: explicit question phrase, explicit `kind:` tag,
recognized section, then checkbox as a commitment. For ordinary prose bullets,
the section supplies the kind. Explicit tags remain supported for mixed notes.

## Bullet text and questions

`-`, `*`, and `+` bullets are supported. A leading bold label supplies a short
title, with its trailing colon removed. Original text stays in `detail`. Indented
continuation lines are included in the same candidate. Nested bullets are separate
candidates. Fenced code blocks are ignored. Plain paragraphs, tables, ordered lists,
and unrecognized headings outside a recognized ancestor are not inferred.

The case-insensitive phrases **still open**, **awaiting his answer**, and
**unanswered** produce a `question` candidate even in another section. This is a
literal phrase rule, not a language model: review quotations, negations, and
historical wording. A `CLOSED`/`RESOLVED` marker still makes such a question done.
An ordinary word such as “open” by itself does not turn a bullet into a question.

## Status patterns

Status markers are uppercase whole words; Markdown bold or bracket wrappers are
fine. Ordinary lowercase prose such as “the office is closed” is not a marker.

| Marker | Candidate status |
| --- | --- |
| `OPEN` | `open` |
| `RESOLVED`, `CLOSED` | `done` |
| `CONFLICT` | `open`, with an explicit review note |
| Both `OPEN` and a done marker | `open`, with a contradictory-status review note |

Markers take precedence over checkboxes. Without a marker, `[x]`/`[X]` means done;
`[ ]` or no checkbox means open. `CONFLICT` always keeps the candidate open.
No marker increases confidence or approves a row.

## Amount patterns

One distinct dollar amount becomes `amount`: `$276.07`, `$30`, `$1,200.50`, `-$30`,
and `$-30` are supported. Repeating the same numeric amount is fine. Two different
amounts, ranges, malformed grouping, or shorthand such as `$30k` leave `amount`
unset and append a review note. The parser does not add amounts together, select
an outstanding balance, or infer a currency. Use the database's agreed currency.

## Date patterns

The profile recognizes:

- `due 2026-11-19`
- `due Nov 19, 2026` or `due November 19 2026`
- Optional `:`/`=` or `on` after `due`; English month abbreviations may have a period.
- A standalone parenthesized ISO date, such as `(2026-10-30)`.

Explicit `due` dates take precedence over parenthesized dates. If there is no
`due` phrase, a single distinct parenthesized date is proposed as `due_date` with
the note **“verify it is a deadline, not a note date.”** Clear that field during
review when it describes provenance or an event instead. Creation/update dates
remain the date of import; the parser does not rewrite them.

Dates require a full four-digit year and must be valid calendar dates. Multiple
distinct dates of the selected pattern leave `due_date` unset. An incomplete or
unrecognized `due` phrase also leaves it unset, even when a parenthesized date is
present. No relative date, missing year, or numeric locale convention is guessed.

## Review, apply, and retries

Review notes are appended to `detail` as `[Import review: ...]` so the existing
JSONL format and schema remain unchanged. Resolve those notes while reviewing;
unapproved rows are skipped even if you pass `--apply`.

```bash
# After reviewing and changing approved to true on accepted rows:
python3 memory.py import local/new-preview.import.jsonl
python3 memory.py import local/new-preview.import.jsonl --apply
```

Keys and source locations remain deterministic for an unchanged bullet. Reusing
the reviewed file skips already imported rows. Changing a source line's location
can generate a new candidate; check for semantic duplicates before applying.
Switching profiles does not authorize rewriting an imported fact. If an existing
key/source has different extracted content, explicitly supersede that row.

The synthetic fixture in [examples/memory-profile.md](../examples/memory-profile.md)
produces **11 unapproved candidates**. Regression tests cover extraction, unknown
prose, section boundaries, conflicts, invalid dates, sensitive-looking continuation
lines, and the full preview → review → apply → retry flow. Real private notes are
not part of the repository or test suite.

To support another actual heading, extend `SECTION_KINDS` in `memory_profile.py`
and add a synthetic regression example. Add explicit patterns only when needed;
keep the approval gate independent of extraction.
