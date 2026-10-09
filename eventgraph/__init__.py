"""Predefined events, typed result connections, and multi-actor experience."""

from .errors import EventGraphError, MissingFlowUpdate, NotEnabled, UndefinedInput, ValidationError
from .flows import Flow, TableFlow
from .graph import EventGraph, MutationReport
from .models import Connection, Event, EventSchema, Execution, History, InputKind, Result, ResultRecord, TimeWindow

__all__ = [
    "Connection", "Event", "EventGraph", "EventGraphError", "EventSchema", "Execution",
    "Flow", "History", "InputKind", "MissingFlowUpdate", "MutationReport", "NotEnabled",
    "Result", "ResultRecord", "TableFlow", "TimeWindow", "UndefinedInput", "ValidationError",
]
