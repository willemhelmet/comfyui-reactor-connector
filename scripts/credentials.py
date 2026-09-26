"""Prove blank server keys, secret widget names, and flat API prompts."""

import os
import tempfile
from pathlib import Path
from collections.abc import Iterator
from contextlib import contextmanager
from ..src.errors import ConnectorError
from .workflows.prompt import check_flat_prompts
from .nodes.widgets import is_secret_widget_name, reject_secret_widget_names, widget_identifiers
from ..src.credentials import credential_source, parse_credential, read_credential, save_credential

SAVED_VALUE = "saved-reactor-key"

SERVER_VALUE = "server-reactor-key"

BLOCKED_NAMES = ("api_key", "API-KEY", "password", "secret", "token", "user_token")

ALLOWED_NAMES = ("duration_seconds", "prompt", "seed", "tokenizer")


def main() -> int:
    """Run the credential, widget-name, and flat-prompt proofs."""
    prove_credentials()
    prove_secret_names()
    check_flat_prompts()
    return 0


@contextmanager
def assigned_server_key(value: str | None) -> Iterator[None]:
    """Set or remove REACTOR_API_KEY for one proof."""
    name = "REACTOR_API_KEY"
    saved = os.environ.get(name)
    was_set = name in os.environ
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    try:
        yield
    finally:
        if was_set and saved is not None:
            os.environ[name] = saved
        else:
            os.environ.pop(name, None)


def prove_credentials() -> None:
    """Run key precedence proofs in private temporary directories."""
    with tempfile.TemporaryDirectory() as raw:
        directory = Path(raw)
        save_credential(directory, parse_credential(SAVED_VALUE))
        prove_blank_server_key(directory)
        prove_server_key_wins(directory)
        prove_spaced_server_key(directory)
    with tempfile.TemporaryDirectory() as raw:
        prove_blank_without_file(Path(raw))


def prove_blank_server_key(directory: Path) -> None:
    """Leave the saved key in effect when the server variable is blank."""
    for value in ("", " \t", None):
        with assigned_server_key(value):
            if credential_source(directory) != "saved" or read_credential(directory).reveal() != SAVED_VALUE:
                msg = "A blank server key must read the saved key."
                raise ValueError(msg)


def prove_server_key_wins(directory: Path) -> None:
    """Prefer a non-empty environment key over the saved key."""
    with assigned_server_key(SERVER_VALUE):
        if credential_source(directory) != "environment" or read_credential(directory).reveal() != SERVER_VALUE:
            msg = "A non-empty server key must take precedence."
            raise ValueError(msg)


def prove_spaced_server_key(directory: Path) -> None:
    """Keep a server key with internal spaces set and invalid."""
    with assigned_server_key("bad key"):
        if credential_source(directory) != "environment":
            msg = "A spaced server key must still override the saved key."
            raise ValueError(msg)
        try:
            read_credential(directory)
        except ConnectorError:
            return
    msg = "A spaced server key must stay invalid."
    raise ValueError(msg)


def prove_blank_without_file(directory: Path) -> None:
    """Treat a blank server key without a saved file as missing."""
    with assigned_server_key("   "):
        if credential_source(directory) != "missing":
            msg = "A blank server key without a file must be missing."
            raise ValueError(msg)
        try:
            read_credential(directory)
        except ConnectorError:
            return
    msg = "A missing key must fail."
    raise ValueError(msg)


def prove_secret_names() -> None:
    """Reject secret-looking widget ids and keep ordinary ids."""
    for name in BLOCKED_NAMES:
        if not is_secret_widget_name(name):
            msg = f"{name} must be rejected."
            raise ValueError(msg)
    for name in ALLOWED_NAMES:
        if is_secret_widget_name(name):
            msg = f"{name} must be allowed."
            raise ValueError(msg)
    child = SampleWidget("api_key")
    option = SampleOption([child])
    parent = SampleWidget("prompt", [option])
    if parent.id != "prompt" or child.id != "api_key" or option.inputs != [child]:
        msg = "Nested widget ids must stay readable."
        raise ValueError(msg)
    names = widget_identifiers([parent])
    try:
        reject_secret_widget_names("ReactorIncExample", names)
    except ValueError:
        return
    msg = "A secret widget name must fail schema checks."
    raise ValueError(msg)


class SampleOption:
    """Stand in for one combo option that owns child inputs."""

    def __init__(self, inputs: list[object]) -> None:
        """Store the child inputs a combo option would serialize."""
        self.inputs = inputs


class SampleWidget:
    """Stand in for one node widget and its optional combo children."""

    def __init__(self, identifier: str, options: list[object] | None = None) -> None:
        """Store an id and optional nested combo options."""
        self.id = identifier
        self.options = [] if options is None else options


if __name__ == "__main__":
    raise SystemExit(main())
