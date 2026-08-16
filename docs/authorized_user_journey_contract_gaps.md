# Authorized user journey: contract gaps

This note records the production contracts that must be approved before the
remaining `Сегодня`, assessment-period, organization-management, and analytics
work can be implemented. It deliberately defines no score formula, threshold,
reporting relationship, or permission escalation.

## Existing safe foundations

- Company timezone is required; a venue may override it, otherwise company
  timezone is inherited.
- Venue access is derived from active account memberships, access-profile
  permissions, and explicit assignment scope. A nullable venue does not grant
  access to all venues.
- Assessment metric APIs return separately identified components and declare
  `components_only`; composite score, target, and overdue values remain absent.
- Employee assignments, invitations, companies, venues, and assessment records
  retain their existing status/revoke/archive semantics. Historical records are
  not hard-deleted by the user-journey UI.

## 1. Today summary contract

Proposed read-only endpoint:

```text
GET /api/v1/account/today-summary?company_id=<authorized>&venue_id=<authorized?>
```

The strict response should contain:

- resolved company and optional venue display context;
- resolved operational timezone and operational date;
- effective access category and safe scope summary;
- metric availability (`available`, `partial`, `insufficient`, `unavailable`);
- approved current value and unit, or `null`;
- approved previous comparable value, delta, and delta unit, or `null`;
- comparison period boundaries and completeness/sample counts;
- stable destination filter values for an authorized drill-down.

Required product decisions:

1. authoritative daily efficiency formula and version;
2. minimum evidence/completeness rules;
3. previous-day comparison semantics and exact delta unit.

Until approved, the UI may show only the current separately identified
components and an honest unavailable state.

## 2. Own-assessment period query

Proposed endpoint extension:

```text
GET /api/v1/account/assessment-assignments
    ?company_id=<authorized>
    &date_from=YYYY-MM-DD
    &date_to=YYYY-MM-DD
    &limit=<bounded>
    &cursor=<opaque?>
```

Server requirements:

- resolve the selected company/venue timezone before deriving boundaries;
- treat `date_from` and `date_to` as inclusive operational dates;
- reject `date_from > date_to` and unbounded ranges;
- return selected timezone and normalized boundaries in the response;
- preserve own-assessment semantics for managers;
- use a stable cursor/count contract so pagination cannot hide results;
- invalidate responses by company, range, session lifecycle, and request
  generation in the client.

Required product decision: which assignment/attempt timestamp determines
membership in a period (assigned, started, last saved, submitted, or a typed
combination). Presets cannot be authoritative until this is chosen.

## 3. Organization management projection

Proposed read models:

```text
GET /api/v1/account/organization-management/context
GET /api/v1/account/organization-management/employees
GET /api/v1/account/organization-management/venues
```

All responses must be permission- and scope-filtered on the server. The access
structure is not an HR reporting hierarchy. It may represent only:

- organization-wide authority;
- explicit venue scope;
- employees without venue assignment;
- pending/inactive membership states.

Mutations for changing scope, revoking a membership, and archiving/restoring a
venue require separate typed operations with idempotency, concurrency control,
last-owner protection, audit evidence, and dependency summaries. No such UI
mutation is enabled until those contracts exist.

Required product decision: whether true manager-to-subordinate reporting lines
are needed. If yes, they require a separate additive domain model and migration.

## 4. Analytics filter and report contract

Proposed read-only endpoints:

```text
GET  /api/v1/account/assessment-analytics/options?company_id=<authorized>
POST /api/v1/account/assessment-analytics/reports
GET  /api/v1/account/assessment-analytics/reports/<opaque-id>/venues
GET  /api/v1/account/assessment-analytics/reports/<opaque-id>/templates
```

The options response must expose only authorized companies, venues, and
published assessment types/templates. The report request should contain
authorized selections and explicit primary/comparison ranges. The response must
state:

- scope and timezone-normalized periods;
- formula/methodology version;
- value and unit only when authoritative;
- completeness and sample counts;
- separately typed venue/template/component breakdowns;
- comparison value/delta/unit when approved;
- bounded drill-down cursors.

Aggregate responses must not include raw answers, comments, phone numbers, or
other employee PII.

Required product decisions:

1. multi-venue aggregation method and weighting;
2. comparison unit and comparability requirements;
3. low-indicator ranking method, missing/not-applicable treatment, ties, and
   minimum evidence threshold.

Until approved, the UI keeps the current server-returned components separate
and does not label any component as a composite or a “worst” indicator.

## 5. Capability projection

The frontend must not infer access from role titles. A typed bootstrap
capability projection should eventually expose operation-level booleans and a
safe scope summary derived from the existing authorization service, for example:

```text
today.read_own
assessment.read_own
template.read
organization.employee_manage
organization.venue_manage
analytics.aggregate_read
team.shell_read
```

This projection is advisory for navigation only. Every endpoint remains the
authoritative authorization boundary. Legacy or ambiguous scope fails closed.

## Migration impact

No migration is justified by the current independent UI slice. Existing models
already express company timezone, optional venue override, organization-wide
scope, explicit venue scope, no-venue assignment, and archive/revoke status.
Any future methodology version, reporting-line model, or new audit contract must
be proposed as its own additive, reversible migration after product approval.
