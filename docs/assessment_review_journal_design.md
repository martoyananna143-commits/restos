# Review journal: bounded design

Status: design only. This document does not authorize a migration, API, import,
or publication of review data.

## Source and boundary

The methodology source is `Бланк аналитики отзывов общий 2026.xlsx`, SHA-256
`a73781bf5a4eea18a6b85a72a705c28cfa656ebab4e615df063b1ff8ba87d94b`.
It remains read-only and is not imported into the assessment template library.
Historical review rows, guest names, employee names, comments, and decisions are
out of scope.

The source contains a review journal shape: date, review type, category,
verbatim review, causes, decisions, due date, and restaurant. Its category list
is methodology requiring product review: `Диджей` is duplicated and
`Критерий 24` / `Критерий 25` are placeholders. Those values must not become a
production taxonomy automatically.

## Proposed bounded domain

`ReviewJournalEntry` belongs to one Company and one Venue and contains:

- immutable entry identifier;
- review occurrence date and source type;
- approved category identifier;
- verbatim review text as restricted evidence;
- optional structured cause records;
- optional corrective-action records with responsible Account, due date, and
  lifecycle status;
- created/updated audit timestamps.

Categories are company-scoped, versioned reference data. Corrective actions are
separate child records so ownership and status changes are auditable. Deleting a
category must not erase historical entries.

## Metric integration

Review data is a later external confirming signal, never an assessment answer.
Only a reviewed category-to-metric mapping may create a normalized observation
for `taste`, `speed`, `service`, `space`, or another existing metric. Until a
normalization policy and category mapping are approved, dashboard output must
show review counts separately and must not blend them into restaurant scores.

No composite restaurant score is defined by this design.

## Security and access

- Company/Venue authorization is server-side and fail-closed.
- Verbatim reviews, causes, decisions, guest identifiers, and responsible people
  are excluded from aggregate dashboard responses.
- Manager drilldown may expose restricted evidence only through a separate,
  audited endpoint and an explicit permission.
- Public DTOs are strict; mutations are `private, no-store`; browser storage and
  sensitive logging are prohibited.
- Bounds are required for text, category count, cause/action count, and query
  period before implementation.

## Product decisions required before implementation

1. Final category taxonomy and treatment of duplicated/placeholding categories.
2. Review source types and whether a guest identity is stored at all.
3. Corrective-action statuses, responsibility rules, and overdue semantics.
4. Category-to-metric mappings and the normalization formula.
5. Retention, redaction, deletion, and restricted drilldown policy.
6. Whether review counts appear on the first dashboard release before normalized
   metric observations exist.

Until these decisions are approved, the only executable use of this workbook is
its filename/SHA provenance in the import inventory.
