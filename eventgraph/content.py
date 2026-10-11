"""The only presentation contract shared by opaque node content objects."""

from dataclasses import dataclass

from .errors import ValidationError


def check_description(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or any(c in value for c in "\r\n"):
        raise ValidationError("content.description must be a non-empty single-line string")
    return value


def describe_content(content: object) -> str:
    """Read the public summary without inspecting the content implementation."""
    return check_description(getattr(content, "description", None))


@dataclass(frozen=True)
class NodeContent:
    """Generic descriptive content; applications may use their own object types.

    data is opaque to the graph and renderer. Treat nested data as immutable.
    The built-in JSON codec requires data to consist of JSON-native values.
    """

    description: str
    data: object = None

    def __post_init__(self) -> None:
        check_description(self.description)
