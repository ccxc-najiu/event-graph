"""Immutable event definitions, ports, connections, and execution records."""

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from types import MappingProxyType
from collections.abc import Mapping

from .errors import UndefinedInput, ValidationError
from .content import describe_content
from .flows import Flow, ids


def check_id(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} must be a non-empty string")


def check_time(value: float) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value):
        raise ValidationError("world time must be a finite number")


@dataclass(frozen=True)
class TimeWindow:
    """Inclusive world-clock bounds; None means unbounded. Units are caller-defined."""

    start: float | None = None
    end: float | None = None

    def __post_init__(self) -> None:
        for value in (self.start, self.end):
            if value is not None:
                check_time(value)
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValidationError("time window start must not exceed end")

    def contains(self, time: float) -> bool:
        check_time(time)
        return (self.start is None or time >= self.start) and (
            self.end is None or time <= self.end
        )


@dataclass(frozen=True)
class Event:
    """Node definition with opaque content interpreted by derived event classes.

    Content is not deep-frozen. Treat it as immutable after insertion; validation
    hooks must not mutate it or external state, so graph updates stay atomic.
    """

    id: str
    roles: tuple[str, ...]
    content: object
    time: TimeWindow = field(default_factory=TimeWindow)
    locations: frozenset[str] = field(default_factory=frozenset)
    description: str = ""

    def __post_init__(self) -> None:
        check_id(self.id, "event ID")
        describe_content(self.content)
        if isinstance(self.roles, str):
            raise ValidationError("roles must be a collection")
        roles = tuple(self.roles)
        if len(ids(roles, "roles")) != len(roles):
            raise ValidationError("role names must be unique")
        object.__setattr__(self, "roles", roles)
        object.__setattr__(self, "locations", ids(self.locations, "locations"))
        if not isinstance(self.time, TimeWindow):
            raise ValidationError("event time must be a TimeWindow")

    def validate_content(self, related_ids: frozenset[str], output_ids: frozenset[str]) -> None:
        """Derived classes validate content against the candidate event interface."""

    def resolve(self, inputs: frozenset[str]) -> frozenset[str]:
        """Derived classes interpret content and return declared result IDs."""
        raise UndefinedInput(f"event {self.id}: content has no execution behavior")


@dataclass(frozen=True)
class FlowEvent(Event):
    """Executable event whose content is a Flow implementation."""

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.content, Flow):
            raise ValidationError("FlowEvent content must implement Flow")

    def validate_content(self, related_ids: frozenset[str], output_ids: frozenset[str]) -> None:
        self.content.validate(related_ids, output_ids)

    def resolve(self, inputs: frozenset[str]) -> frozenset[str]:
        return self.content.resolve(inputs)


@dataclass(frozen=True)
class Result:
    """Output-port definition. Empty recipient_roles means a world-level result."""

    id: str
    event_id: str
    recipient_roles: tuple[str, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        check_id(self.id, "result ID")
        check_id(self.event_id, "result owner")
        if isinstance(self.recipient_roles, str):
            raise ValidationError("recipient_roles must be a collection")
        roles = tuple(self.recipient_roles)
        if len(ids(roles, "recipient roles")) != len(roles):
            raise ValidationError("recipient roles must be unique")
        object.__setattr__(self, "recipient_roles", roles)


class InputKind(str, Enum):
    TRIGGER = "trigger"
    RELATED = "related"


@dataclass(frozen=True)
class Connection:
    source_result: str
    target_event: str
    kind: InputKind
    target_role: str | None = None

    def __post_init__(self) -> None:
        check_id(self.source_result, "source result")
        check_id(self.target_event, "target event")
        try:
            object.__setattr__(self, "kind", InputKind(self.kind))
        except ValueError as exc:
            raise ValidationError("connection kind must be trigger or related") from exc
        if self.target_role is not None:
            check_id(self.target_role, "target role")


@dataclass(frozen=True)
class EventSchema:
    event: Event
    trigger_conditions: frozenset[str]
    related_items: frozenset[str]
    outputs: frozenset[str]


@dataclass(frozen=True)
class ResultRecord:
    """Historical snapshot: still readable after a definition is replaced."""

    definition: Result
    recipients: frozenset[str]

    @property
    def result_id(self) -> str:
        return self.definition.id


@dataclass(frozen=True)
class Execution:
    id: str
    event_id: str
    graph_revision: int
    time: float
    location: str
    participants: Mapping[str, str]
    inputs: frozenset[str]
    results: tuple[ResultRecord, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "participants", MappingProxyType(dict(self.participants)))
        object.__setattr__(self, "inputs", frozenset(self.inputs))
        object.__setattr__(self, "results", tuple(self.results))


class History:
    """Append-only execution ledger; querying does not create absent results."""

    def __init__(self) -> None:
        self._executions: list[Execution] = []
        self._ids: set[str] = set()

    @property
    def executions(self) -> tuple[Execution, ...]:
        return tuple(self._executions)

    def for_actor(self, actor: str) -> tuple[ResultRecord, ...]:
        return tuple(
            record for execution in self._executions for record in execution.results
            if actor in record.recipients
        )

    def experiences(self, actor: str) -> tuple[Execution, ...]:
        """Include participation even if that execution produced no personal result."""
        return tuple(e for e in self._executions if actor in e.participants.values())

    def _append(self, execution: Execution) -> None:
        if execution.id in self._ids:
            raise ValidationError(f"duplicate execution ID: {execution.id}")
        if self._executions and execution.time < self._executions[-1].time:
            raise ValidationError("history time cannot move backwards")
        self._executions.append(execution)
        self._ids.add(execution.id)

    def _matches(
        self, connection: Connection, participants: Mapping[str, str], time: float
    ) -> bool:
        actors = set(participants.values())
        for execution in self._executions:
            if execution.time > time:
                continue
            for record in execution.results:
                if record.result_id != connection.source_result:
                    continue
                if connection.target_role is not None:
                    if participants[connection.target_role] in record.recipients:
                        return True
                elif not record.recipients or record.recipients & actors:
                    return True
        return False

