"""Public errors; failed mutations and executions leave stored data unchanged."""


class EventGraphError(Exception):
    """Base class for library errors."""


class ValidationError(EventGraphError, ValueError):
    """Invalid definition, connection, or flow."""


class MissingFlowUpdate(ValidationError):
    """An existing event's interface changed without an explicit flow update."""


class NotEnabled(EventGraphError):
    """The event's time, location, or prerequisite conditions are not satisfied."""


class UndefinedInput(EventGraphError):
    """A runtime input falls outside the flow's declared domain."""

