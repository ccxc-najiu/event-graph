"""Transactional graph mutations and explicitly chosen event execution."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from uuid import uuid4

from .errors import MissingFlowUpdate, NotEnabled, ValidationError
from .flows import Flow, ids
from .models import (
    Connection, Event, EventSchema, Execution, History, InputKind,
    Result, ResultRecord, check_id, check_time,
)


@dataclass(frozen=True)
class MutationReport:
    revision: int
    added_events: frozenset[str]
    added_results: frozenset[str]
    removed_results: frozenset[str]
    updated_events: frozenset[str]


class EventGraph:
    """An event-centred port graph, not a path that characters must traverse.

    Definition updates are all-or-nothing for graph-owned data. Single-threaded;
    custom Flow methods must not mutate the graph or external state in validation.
    """

    def __init__(self) -> None:
        self._events: dict[str, Event] = {}
        self._results: dict[str, Result] = {}
        self._connections: tuple[Connection, ...] = ()
        self._incoming: dict[str, tuple[Connection, ...]] = {}
        self._outgoing: dict[str, tuple[Connection, ...]] = {}
        self._retired_results: set[str] = set()
        self._revision = 0

    @property
    def events(self) -> Mapping[str, Event]:
        return MappingProxyType(self._events)

    @property
    def results(self) -> Mapping[str, Result]:
        return MappingProxyType(self._results)

    @property
    def connections(self) -> tuple[Connection, ...]:
        return self._connections

    @property
    def revision(self) -> int:
        return self._revision

    def schema(self, event_id: str) -> EventSchema:
        return self._schema(event_id, self._events, self._results, self._connections)

    def consumers(self, result_id: str) -> tuple[Connection, ...]:
        if result_id not in self._results:
            raise ValidationError(f"unknown result: {result_id}")
        return self._outgoing.get(result_id, ())

    def append(
        self, *, events: Iterable[Event] = (), results: Iterable[Result] = (),
        connections: Iterable[Connection] = (),
        flow_updates: Mapping[str, Flow] | None = None,
    ) -> MutationReport:
        """Add definitions/connections and explicitly update affected flows atomically.

        Connections may reference existing results as well as newly added ones.
        Every existing event with a changed input/output interface needs an entry
        in flow_updates, even when intentionally reusing its previous Flow.
        """
        next_events = dict(self._events)
        next_results = dict(self._results)
        for event in events:
            if event.id in next_events:
                raise ValidationError(f"duplicate event ID: {event.id}")
            next_events[event.id] = event
        for result in results:
            if result.id in next_results or result.id in self._retired_results:
                raise ValidationError(f"duplicate or retired result ID: {result.id}")
            next_results[result.id] = result
        return self._commit(
            next_events, next_results, self._connections + tuple(connections),
            dict(flow_updates or {}), removed=frozenset(),
        )

    def replace_result(
        self, old_result: str, new_result: Result, *,
        connections: Iterable[Connection] = (),
        flow_updates: Mapping[str, Flow] | None = None,
    ) -> MutationReport:
        """Retire one output port, remove its edges, and add a replacement port.

        Reconnection is explicit, never inferred. Existing History snapshots are
        unaffected. Retired IDs cannot be reused for a different meaning.
        """
        if old_result not in self._results:
            raise ValidationError(f"unknown result: {old_result}")
        if new_result.id in self._results or new_result.id in self._retired_results:
            raise ValidationError(f"replacement needs a fresh result ID: {new_result.id}")
        if new_result.event_id != self._results[old_result].event_id:
            raise ValidationError("replacement must belong to the same event")
        next_results = dict(self._results)
        del next_results[old_result]
        next_results[new_result.id] = new_result
        remaining = tuple(c for c in self._connections if c.source_result != old_result)
        return self._commit(
            dict(self._events), next_results, remaining + tuple(connections),
            dict(flow_updates or {}), removed=frozenset({old_result}),
        )

    @staticmethod
    def _schema(event_id, events, results, connections) -> EventSchema:
        if event_id not in events:
            raise ValidationError(f"unknown event: {event_id}")
        return EventSchema(
            event=events[event_id],
            trigger_conditions=frozenset(
                c.source_result for c in connections
                if c.target_event == event_id and c.kind is InputKind.TRIGGER
            ),
            related_items=frozenset(
                c.source_result for c in connections
                if c.target_event == event_id and c.kind is InputKind.RELATED
            ),
            outputs=frozenset(r.id for r in results.values() if r.event_id == event_id),
        )

    def _commit(self, events, results, connections, updates, *, removed) -> MutationReport:
        if not set(updates) <= set(events):
            raise ValidationError(f"flow update references unknown events: {set(updates) - set(events)}")
        for event_id, flow in updates.items():
            events[event_id] = replace(events[event_id], flow=flow)
        for result in results.values():
            if result.event_id not in events:
                raise ValidationError(f"unknown result owner: {result.event_id}")
            if not set(result.recipient_roles) <= set(events[result.event_id].roles):
                raise ValidationError(f"unknown recipient role on result: {result.id}")
        seen: set[tuple[str, str]] = set()
        incoming: dict[str, list[Connection]] = {key: [] for key in events}
        outgoing: dict[str, list[Connection]] = {key: [] for key in results}
        for connection in connections:
            if connection.source_result not in results or connection.target_event not in events:
                raise ValidationError(f"dangling connection: {connection}")
            pair = (connection.source_result, connection.target_event)
            if pair in seen:
                raise ValidationError(
                    "one result may connect to an event only once; trigger and related "
                    f"sets must be disjoint: {pair}"
                )
            seen.add(pair)
            if connection.target_role is not None and connection.target_role not in events[connection.target_event].roles:
                raise ValidationError(f"unknown target role: {connection.target_role}")
            incoming[connection.target_event].append(connection)
            outgoing[connection.source_result].append(connection)
        changed = set()
        for event_id in self._events:
            old_outputs = self.schema(event_id).outputs
            new_outputs = self._schema(event_id, events, results, connections).outputs
            if old_outputs != new_outputs or set(self._incoming[event_id]) != set(incoming[event_id]):
                changed.add(event_id)
        missing = changed - set(updates)
        if missing:
            raise MissingFlowUpdate(f"explicit flow updates required for: {sorted(missing)}")
        for event_id, event in events.items():
            schema = self._schema(event_id, events, results, connections)
            event.flow.validate(schema.related_items, schema.outputs)
        report = MutationReport(
            revision=self._revision + 1,
            added_events=frozenset(set(events) - set(self._events)),
            added_results=frozenset(set(results) - set(self._results)),
            removed_results=removed,
            updated_events=frozenset((changed | set(updates)) & set(self._events)),
        )
        # No caller code executes after this point: commit graph-owned state together.
        self._events = events
        self._results = results
        self._connections = tuple(connections)
        self._incoming = {key: tuple(value) for key, value in incoming.items()}
        self._outgoing = {key: tuple(value) for key, value in outgoing.items()}
        self._retired_results.update(removed)
        self._revision = report.revision
        return report

    def inputs_for(
        self, event_id: str, history: History, *, participants: Mapping[str, str],
        time: float, location: str,
    ) -> frozenset[str]:
        """Check activation and return the present related-input combination."""
        schema = self.schema(event_id)
        event = schema.event
        check_time(time)
        if set(participants) != set(event.roles):
            raise ValidationError(f"participants must bind exactly these roles: {event.roles}")
        for actor in participants.values():
            check_id(actor, "actor ID")
        if not event.time.contains(time):
            raise NotEnabled(f"outside event time window: {event_id}")
        if event.locations and location not in event.locations:
            raise NotEnabled(f"outside event locations: {event_id}")
        found = {
            c.source_result for c in self._incoming[event_id]
            if history._matches(c, participants, time)
        }
        missing = schema.trigger_conditions - found
        if missing:
            raise NotEnabled(f"missing trigger results: {sorted(missing)}")
        return frozenset(found & schema.related_items)

    def is_enabled(self, event_id: str, history: History, **context) -> bool:
        try:
            self.inputs_for(event_id, history, **context)
        except NotEnabled:
            return False
        return True

    def execute(
        self, event_id: str, history: History, *, participants: Mapping[str, str],
        time: float, location: str, execution_id: str | None = None,
    ) -> Execution:
        """Run one explicitly selected event and append its joint outcome atomically."""
        participants = dict(participants)
        inputs = self.inputs_for(
            event_id, history, participants=participants, time=time, location=location
        )
        chosen_id = str(uuid4()) if execution_id is None else execution_id
        check_id(chosen_id, "execution ID")
        if any(e.id == chosen_id for e in history.executions):
            raise ValidationError(f"duplicate execution ID: {chosen_id}")
        if history.executions and time < history.executions[-1].time:
            raise ValidationError("history time cannot move backwards")
        output = ids(self._events[event_id].flow.resolve(inputs), "runtime outputs")
        if not output <= self.schema(event_id).outputs:
            raise ValidationError(f"flow returned undeclared outputs: {output}")
        records = tuple(
            ResultRecord(
                definition=self._results[result_id],
                recipients=frozenset(
                    participants[role] for role in self._results[result_id].recipient_roles
                ),
            )
            for result_id in sorted(output)
        )
        execution = Execution(
            chosen_id, event_id, self._revision, time, location,
            participants, inputs, records,
        )
        history._append(execution)
        return execution

