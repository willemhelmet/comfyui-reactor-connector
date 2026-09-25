"""Reject widget names that would save secrets in workflow JSON."""

from collections.abc import Sequence

SECRET_NAME_PARTS = frozenset({"password", "secret", "token"})


def is_secret_widget_name(name: str) -> bool:
    """Return whether a widget id would serialize a credential into a workflow."""
    normalized = name.casefold().replace("-", "_")
    if "apikey" in normalized.replace("_", ""):
        return True
    return bool(set(normalized.split("_")) & SECRET_NAME_PARTS)


def widget_identifiers(inputs: Sequence[object]) -> list[str]:
    """List widget ids, including children nested under a combo option."""
    names: list[str] = []
    for item in inputs:
        names.extend(names_from_input(item))
    return names


def names_from_input(item: object) -> list[str]:
    """Collect one input id and ids nested under its combo options."""
    names: list[str] = []
    identifier = getattr(item, "id", None)
    if isinstance(identifier, str):
        names.append(identifier)
    options = getattr(item, "options", None)
    if not isinstance(options, list):
        return names
    for option in options:
        children = getattr(option, "inputs", None)
        if isinstance(children, list):
            for child in children:
                names.extend(names_from_input(child))
    return names


def reject_secret_widget_names(node_id: str, names: list[str]) -> None:
    """Reject secret-looking widget ids before a workflow can store them."""
    for name in names:
        if is_secret_widget_name(name):
            msg = f"Keep {name} off {node_id}. Store keys in Reactor settings or REACTOR_API_KEY."
            raise ValueError(msg)
