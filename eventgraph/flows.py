"""Predefined processes consume combinations of related result IDs."""

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .errors import UndefinedInput, ValidationError
from .content import check_description


def ids(values: Iterable[str], label: str) -> frozenset[str]:
    if isinstance(values, str):
        raise ValidationError(f"{label} must be a collection, not a string")
    result = frozenset(values)
    if any(not isinstance(value, str) or not value.strip() for value in result):
        raise ValidationError(f"{label} must contain non-empty string IDs")
    return result


class Flow(ABC):
    """Extend this class for a decision graph, state machine, or stochastic rule.

    validate() must be side-effect-free. resolve() receives only the related
    results that are present, never missing prerequisites or unrelated history.
    Implementations should be immutable: graph transactions cannot roll back
    arbitrary side effects in caller-supplied Python objects.
    """

    description: str = "根据关联结果决定本次事件的输出。"

    def validate(
        self, related_ids: frozenset[str], output_ids: frozenset[str]
    ) -> None:
        """Override to validate a custom process against its event interface."""

    @abstractmethod
    def resolve(self, inputs: frozenset[str]) -> frozenset[str]:
        """Return one joint outcome: zero or more declared output result IDs."""


class UnconfiguredFlow(Flow):
    """An editable definition without execution rules; never invent an outcome."""

    def __init__(self, description: str = "尚未配置事件的执行规则。") -> None:
        self.description = check_description(description)

    def resolve(self, inputs: frozenset[str]) -> frozenset[str]:
        raise UndefinedInput("event flow has not been configured")


@dataclass(frozen=True, init=False)
class TableFlow(Flow):
    """Exact combination lookup, with optional fallback and explicit domain.

    With no default/domain, all 2**N related-input combinations must be covered.
    A default avoids enumerating them. input_domain is an author assertion of
    reachability, not a reachability proof; unexpected inputs fail at runtime.
    """

    cases: Mapping[frozenset[str], frozenset[str]]
    default: frozenset[str] | None
    input_domain: frozenset[frozenset[str]] | None
    description: str

    def __init__(
        self,
        cases: Mapping[frozenset[str], Iterable[str]] | None = None,
        *,
        default: Iterable[str] | None = None,
        input_domain: Iterable[Iterable[str]] | None = None,
        description: str = "根据关联结果查表，确定本次事件的输出。",
    ) -> None:
        object.__setattr__(self, "description", check_description(description))
        normalized = {
            ids(key, "case inputs"): ids(value, "case outputs")
            for key, value in (cases or {}).items()
        }
        object.__setattr__(self, "cases", MappingProxyType(normalized))
        object.__setattr__(
            self, "default", None if default is None else ids(default, "default")
        )
        object.__setattr__(
            self,
            "input_domain",
            None if input_domain is None else frozenset(
                ids(item, "input domain") for item in input_domain
            ),
        )

    def validate(self, related_ids: frozenset[str], output_ids: frozenset[str]) -> None:
        inputs = set(self.cases)
        if self.input_domain is not None:
            inputs.update(self.input_domain)
        for combination in inputs:
            if not combination <= related_ids:
                raise ValidationError(
                    f"flow reads undeclared related results: {combination - related_ids}"
                )
        outcomes = list(self.cases.values())
        if self.default is not None:
            outcomes.append(self.default)
        for outcome in outcomes:
            if not outcome <= output_ids:
                raise ValidationError(
                    f"flow produces undeclared results: {outcome - output_ids}"
                )
        if self.input_domain is not None:
            if not set(self.cases) <= self.input_domain:
                raise ValidationError("cases must be inside the declared input domain")
            if self.default is None and set(self.cases) != self.input_domain:
                raise ValidationError("flow does not cover its declared input domain")
        elif self.default is None and len(self.cases) != 2 ** len(related_ids):
            raise ValidationError(
                "flow must cover every related-input combination, provide a default, "
                "or declare an input_domain"
            )

    def resolve(self, inputs: frozenset[str]) -> frozenset[str]:
        if self.input_domain is not None and inputs not in self.input_domain:
            raise UndefinedInput(f"input combination outside declared domain: {inputs}")
        if inputs in self.cases:
            return self.cases[inputs]
        if self.default is not None:
            return self.default
        raise UndefinedInput(f"no flow case for input combination: {inputs}")
