"""Pure deterministic weighted scoring for immutable assessment versions."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping, Sequence
from uuid import UUID


_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")
_SCORE_QUANTUM = Decimal("0.0001")
_RATIO_QUANTUM = Decimal("0.000001")


class WeightedScoringInvalid(Exception):
    """The published scoring configuration or submitted value is invalid."""


@dataclass(frozen=True)
class WeightedItem:
    item_id: UUID
    answer_type: str
    required: bool
    weight: Decimal | None
    min_value: Decimal | None
    max_value: Decimal | None
    criticality: str
    config: Mapping[str, Any]
    option_values: Mapping[UUID, Decimal]


@dataclass(frozen=True)
class MetricMapping:
    item_id: UUID
    metric_definition_id: UUID
    metric_code: str
    contribution_weight: Decimal
    direction: str


@dataclass(frozen=True)
class ItemScore:
    item_id: UUID
    normalized: Decimal
    critical_failure: bool
    stop_factor_failure: bool


@dataclass(frozen=True)
class WeightedResult:
    numerator: Decimal
    denominator: Decimal
    score_percent: Decimal
    coverage: Decimal
    answered_count: int
    required_count: int
    total_count: int
    eligible_count: int
    excluded_count: int
    critical_failure_count: int
    stop_factor_count: int
    item_scores: tuple[ItemScore, ...]

    def public_document(self, submitted_at: str) -> dict[str, Any]:
        return {
            "scoring_algorithm": "weighted_v1",
            "scoring_version": 1,
            "submitted_at": submitted_at,
            "numerator": _decimal_text(self.numerator),
            "denominator": _decimal_text(self.denominator),
            "score_percent": _decimal_text(self.score_percent),
            "coverage": _decimal_text(self.coverage),
            "answered_count": self.answered_count,
            "required_count": self.required_count,
            "total_count": self.total_count,
            "eligible_count": self.eligible_count,
            "excluded_count": self.excluded_count,
            "critical_failure_count": self.critical_failure_count,
            "stop_factor_count": self.stop_factor_count,
        }


@dataclass(frozen=True)
class MetricResult:
    metric_definition_id: UUID
    metric_code: str
    numerator: Decimal
    denominator: Decimal
    score_percent: Decimal
    coverage: Decimal
    critical_failure_count: int
    stop_factor_count: int
    contributions: tuple[dict[str, Any], ...]


def calculate_weighted_result(
    items: Sequence[WeightedItem],
    answers: Mapping[UUID, Any],
) -> WeightedResult:
    """Calculate one immutable source result without I/O or hidden defaults."""

    if not items:
        raise WeightedScoringInvalid("weighted template has no items")
    item_ids = {item.item_id for item in items}
    if len(item_ids) != len(items):
        raise WeightedScoringInvalid("duplicate weighted item")
    if not set(answers).issubset(item_ids):
        raise WeightedScoringInvalid("answer does not belong to template")

    required_count = sum(item.required for item in items)
    total_weight = _ZERO
    eligible_weight = _ZERO
    numerator = _ZERO
    denominator = _ZERO
    item_scores: list[ItemScore] = []
    excluded_count = 0

    for item in items:
        if item.weight is None or item.weight <= _ZERO:
            raise WeightedScoringInvalid("weighted item requires positive weight")
        total_weight += item.weight
        if item.item_id not in answers:
            if item.required:
                raise WeightedScoringInvalid("required answer is missing")
            excluded_count += 1
            continue
        normalized = _normalize(item, answers[item.item_id])
        eligible_weight += item.weight
        denominator += item.weight
        numerator += normalized * item.weight
        threshold = _critical_threshold(item)
        failed = normalized < threshold
        item_scores.append(
            ItemScore(
                item_id=item.item_id,
                normalized=normalized,
                critical_failure=item.criticality == "critical" and failed,
                stop_factor_failure=item.criticality == "stop_factor" and failed,
            )
        )

    if denominator <= _ZERO:
        raise WeightedScoringInvalid("weighted denominator is zero")
    coverage = (eligible_weight / total_weight).quantize(
        _RATIO_QUANTUM, rounding=ROUND_HALF_UP
    )
    score_percent = (numerator / denominator * _HUNDRED).quantize(
        _SCORE_QUANTUM, rounding=ROUND_HALF_UP
    )
    return WeightedResult(
        numerator=numerator,
        denominator=denominator,
        score_percent=score_percent,
        coverage=coverage,
        answered_count=len(answers),
        required_count=required_count,
        total_count=len(items),
        eligible_count=len(item_scores),
        excluded_count=excluded_count,
        critical_failure_count=sum(score.critical_failure for score in item_scores),
        stop_factor_count=sum(score.stop_factor_failure for score in item_scores),
        item_scores=tuple(item_scores),
    )


def calculate_metric_results(
    result: WeightedResult,
    mappings: Sequence[MetricMapping],
) -> tuple[MetricResult, ...]:
    """Project source item scores into traceable metric components."""

    scores = {score.item_id: score for score in result.item_scores}
    grouped: dict[UUID, list[MetricMapping]] = {}
    codes: dict[UUID, str] = {}
    for mapping in mappings:
        if mapping.contribution_weight <= _ZERO:
            raise WeightedScoringInvalid("metric contribution weight must be positive")
        if mapping.direction not in {"positive", "inverse"}:
            raise WeightedScoringInvalid("invalid metric direction")
        previous = codes.setdefault(mapping.metric_definition_id, mapping.metric_code)
        if previous != mapping.metric_code:
            raise WeightedScoringInvalid("metric definition code mismatch")
        grouped.setdefault(mapping.metric_definition_id, []).append(mapping)

    projected: list[MetricResult] = []
    for metric_id in sorted(grouped, key=str):
        metric_mappings = grouped[metric_id]
        total_weight = sum(
            (mapping.contribution_weight for mapping in metric_mappings), _ZERO
        )
        numerator = _ZERO
        denominator = _ZERO
        critical_count = 0
        stop_factor_count = 0
        contributions: list[dict[str, Any]] = []
        for mapping in metric_mappings:
            score = scores.get(mapping.item_id)
            if score is None:
                contributions.append(
                    {
                        "item_id": str(mapping.item_id),
                        "normalized": None,
                        "source_normalized": None,
                        "weight": _decimal_text(mapping.contribution_weight),
                        "critical_failure": False,
                        "stop_factor_failure": False,
                    }
                )
                continue
            normalized = (
                score.normalized
                if mapping.direction == "positive"
                else _ONE - score.normalized
            )
            numerator += normalized * mapping.contribution_weight
            denominator += mapping.contribution_weight
            critical_count += int(score.critical_failure)
            stop_factor_count += int(score.stop_factor_failure)
            contributions.append(
                {
                    "item_id": str(mapping.item_id),
                    "normalized": _decimal_text(normalized),
                    "source_normalized": _decimal_text(score.normalized),
                    "weight": _decimal_text(mapping.contribution_weight),
                    "critical_failure": score.critical_failure,
                    "stop_factor_failure": score.stop_factor_failure,
                }
            )
        if denominator == _ZERO:
            continue
        projected.append(
            MetricResult(
                metric_definition_id=metric_id,
                metric_code=codes[metric_id],
                numerator=numerator,
                denominator=denominator,
                score_percent=(numerator / denominator * _HUNDRED).quantize(
                    _SCORE_QUANTUM, rounding=ROUND_HALF_UP
                ),
                coverage=(denominator / total_weight).quantize(
                    _RATIO_QUANTUM, rounding=ROUND_HALF_UP
                ),
                critical_failure_count=critical_count,
                stop_factor_count=stop_factor_count,
                contributions=tuple(contributions),
            )
        )
    return tuple(projected)


def _normalize(item: WeightedItem, value: Any) -> Decimal:
    if item.answer_type == "boolean":
        if type(value) is not bool:
            raise WeightedScoringInvalid("invalid boolean score")
        return _ONE if value else _ZERO
    if item.answer_type in {"score", "integer", "decimal"}:
        numeric = _decimal(value)
        return _range_normalize(item, numeric)
    if item.answer_type == "single_choice":
        try:
            option_id = UUID(str(value))
        except (TypeError, ValueError) as error:
            raise WeightedScoringInvalid("invalid scored option") from error
        if option_id not in item.option_values:
            raise WeightedScoringInvalid("scored option has no numeric value")
        return _range_normalize(item, item.option_values[option_id])
    raise WeightedScoringInvalid("answer type is not supported by weighted_v1")


def _range_normalize(item: WeightedItem, value: Decimal) -> Decimal:
    if item.min_value is None or item.max_value is None:
        raise WeightedScoringInvalid("numeric score requires min and max")
    if item.max_value <= item.min_value:
        raise WeightedScoringInvalid("numeric score range must be positive")
    if value < item.min_value or value > item.max_value:
        raise WeightedScoringInvalid("numeric score is outside range")
    return (value - item.min_value) / (item.max_value - item.min_value)


def _critical_threshold(item: WeightedItem) -> Decimal:
    raw = item.config.get("critical_threshold", "1")
    threshold = _decimal(raw)
    if threshold < _ZERO or threshold > _ONE:
        raise WeightedScoringInvalid("critical threshold is outside normalized range")
    return threshold


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise WeightedScoringInvalid("boolean is not numeric")
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise WeightedScoringInvalid("invalid numeric score") from error
    if not numeric.is_finite():
        raise WeightedScoringInvalid("numeric score must be finite")
    return numeric


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")
