"""Convert canvas graphs into ComfyUI `/prompt` payloads."""

import json
from typing import cast
from pathlib import Path
from ...src.state.documents import Json
from ...src.serialization import mapping_value


DYNAMIC_COMBO = "COMFY_DYNAMICCOMBO_V3"

UPLOAD_FLAGS = ("image_upload", "video_upload", "audio_upload", "file_upload")

WIDGET_TYPES = frozenset({"STRING", "INT", "FLOAT", "BOOLEAN", "COMBO", DYNAMIC_COMBO})

SKIPPED_NODE_TYPES = frozenset({"MarkdownNote"})

API_CLIENT_ID = "helios-hello-world"

API_WORKFLOW_SLUGS = frozenset({"helios-01-text-to-video"})


def dump_document(value: dict[str, Json]) -> str:
    """Serialize one workflow document with the repository's JSON layout."""
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def api_document(workflow: dict[str, Json], schemas: dict[str, Json]) -> dict[str, Json]:
    """Return a `/prompt` body for one canvas graph."""
    return {"prompt": api_prompt(workflow, schemas), "client_id": API_CLIENT_ID}


def api_prompt(workflow: dict[str, Json], schemas: dict[str, Json]) -> dict[str, Json]:
    """Map executable nodes to class types and flat input values."""
    links = link_index(workflow)
    prompt: dict[str, Json] = {}
    for value in cast("list[Json]", workflow["nodes"]):
        node = mapping_value(value)
        kind = str(node["type"])
        if kind in SKIPPED_NODE_TYPES or node.get("mode", 0) not in {0, None}:
            continue
        if kind not in schemas:
            msg = f"Add a schema before converting {kind} to an API prompt."
            raise ValueError(msg)
        prompt[str(node["id"])] = {
            "class_type": kind,
            "inputs": node_inputs(node, links, mapping_value(schemas[kind])),
        }
    if not prompt:
        msg = "The API prompt needs at least one executable node."
        raise ValueError(msg)
    require_flat_inputs(prompt)
    return prompt


def link_index(workflow: dict[str, Json]) -> dict[int, list[Json]]:
    """Index canvas links by id as `[source node, output slot]`."""
    indexed: dict[int, list[Json]] = {}
    for value in cast("list[Json]", workflow["links"]):
        link = cast("list[Json]", value)
        indexed[int(cast("int", link[0]))] = [str(link[1]), link[2]]
    return indexed


def node_inputs(node: dict[str, Json], links: dict[int, list[Json]], schema: dict[str, Json]) -> dict[str, Json]:
    """Combine connected sockets with widget values in schema order."""
    inputs = linked_inputs(node, links)
    widgets = [item for item in cast("list[Json]", schema["inputs"]) if mapping_value(item).get("widget")]
    inputs.update(widget_inputs([mapping_value(item) for item in widgets], node.get("widgets_values", [])))
    return inputs


def linked_inputs(node: dict[str, Json], links: dict[int, list[Json]]) -> dict[str, Json]:
    """Read connected inputs as `[node id, slot]` pairs."""
    inputs: dict[str, Json] = {}
    for value in cast("list[Json]", node.get("inputs", [])):
        socket = mapping_value(value)
        link_id = socket.get("link")
        if not isinstance(link_id, int):
            continue
        if link_id not in links:
            msg = f"Connect {socket['name']} before converting the workflow."
            raise ValueError(msg)
        inputs[str(socket["name"])] = links[link_id]
    return inputs


def widget_inputs(widgets: list[dict[str, Json]], values: Json) -> dict[str, Json]:
    """Read saved widget values into flat prompt keys."""
    if not isinstance(values, list):
        msg = "Save widget values as a list before converting the workflow."
        raise TypeError(msg)
    inputs, remaining = consume_widgets(widgets, values, "")
    if remaining:
        msg = "Match widget values to the node schema before converting the workflow."
        raise ValueError(msg)
    return inputs


def consume_widgets(
    widgets: list[dict[str, Json]], values: list[Json], prefix: str
) -> tuple[dict[str, Json], list[Json]]:
    """Read one widget list and return values that belong to later widgets."""
    inputs: dict[str, Json] = {}
    rest = values
    for widget in widgets:
        if widget.get("widget") is False:
            continue
        inputs, rest = consume_widget(widget, rest, prefix, inputs)
    return inputs, rest


def consume_widget(
    widget: dict[str, Json], values: list[Json], prefix: str, inputs: dict[str, Json]
) -> tuple[dict[str, Json], list[Json]]:
    """Read one widget, its seed or upload token, and any DynamicCombo children."""
    name = str(widget["name"])
    value, rest = next_value(values, name)
    rest = drop_extra(widget, rest, extra=bool(widget.get("control_after_generate")))
    rest = drop_extra(widget, rest, extra=any(widget.get(flag) for flag in UPLOAD_FLAGS))
    key = input_name(prefix, name)
    if str(widget.get("type")) == DYNAMIC_COMBO:
        nested, rest = consume_widgets(selected_widgets(widget, value), rest, key)
    else:
        nested = {}
    # Hidden controls still occupy saved slots. `/prompt` does not receive them.
    if widget.get("hidden") is True:
        return inputs, rest
    return {**inputs, key: value, **nested}, rest


def selected_widgets(widget: dict[str, Json], selected: Json) -> list[dict[str, Json]]:
    """Return the widgets saved for the selected DynamicCombo option."""
    if not isinstance(selected, str):
        msg = f"Use a {widget['name']} choice string in the API prompt."
        raise TypeError(msg)
    for value in cast("list[Json]", widget.get("options", [])):
        option = mapping_value(value)
        if option.get("key") == selected:
            groups = option.get("inputs", {})
            return grouped_widgets(mapping_value(groups) if isinstance(groups, dict) else {})
    msg = f"Choose a supported {widget['name']} value before converting the workflow."
    raise ValueError(msg)


def grouped_widgets(groups: dict[str, Json]) -> list[dict[str, Json]]:
    """List required DynamicCombo children before optional children."""
    widgets: list[dict[str, Json]] = []
    for group_name in ("required", "optional"):
        group = groups.get(group_name)
        if isinstance(group, dict):
            widgets.extend(widget_from_spec(name, spec) for name, spec in group.items())
    return widgets


def widget_from_spec(name: str, spec: Json) -> dict[str, Json]:
    """Normalize one nested input pair into the top-level widget shape."""
    if not isinstance(spec, list):
        msg = f"Describe the {name} input as a type and settings pair."
        raise TypeError(msg)
    try:
        kind_value, config = spec
    except ValueError:
        msg = f"Describe the {name} input as a type and settings pair."
        raise TypeError(msg) from None
    if not isinstance(config, dict):
        msg = f"Describe the {name} input as a type and settings pair."
        raise TypeError(msg)
    kind = str(kind_value)
    return {**config, "name": name, "type": kind, "widget": is_prompt_widget(kind, config)}


def is_prompt_widget(kind: str, config: dict[str, Json]) -> bool:
    """Return whether a nested input is stored in widget values."""
    return kind in WIDGET_TYPES and config.get("forceInput") is not True


def next_value(values: list[Json], name: str) -> tuple[Json, list[Json]]:
    """Take the next saved widget value."""
    if not values:
        msg = f"Supply a saved value for {name}."
        raise ValueError(msg)
    return values[0], values[1:]


def drop_extra(widget: dict[str, Json], values: list[Json], *, extra: bool) -> list[Json]:
    """Drop a frontend-only token that follows a widget value."""
    if not extra:
        return values
    _, rest = next_value(values, str(widget["name"]))
    return rest


def input_name(prefix: str, name: str) -> str:
    """Join a DynamicCombo path with dots, matching ComfyUI prompt keys."""
    return f"{prefix}.{name}" if prefix else name


def require_flat_inputs(prompt: dict[str, Json]) -> None:
    """Reject nested objects, which `/prompt` does not accept for DynamicCombo inputs."""
    for node_id, value in prompt.items():
        node = mapping_value(value)
        for name, item in mapping_value(node["inputs"]).items():
            if isinstance(item, dict):
                msg = f"Use a flat value for {node['class_type']} input {name} on node {node_id}."
                raise TypeError(msg)


def check_flat_prompts() -> None:
    """Fail on a nested SaveVideo format and accept the shipped Helios API file."""
    reject_nested_format()
    require_flat_save_video(shipped_helios_prompt())


def reject_nested_format() -> None:
    """Require the flat-key check to reject a nested format object."""
    sample: dict[str, Json] = {"4": {"class_type": "SaveVideo", "inputs": {"format": {"codec": "auto"}}}}
    try:
        require_flat_inputs(sample)
    except TypeError:
        return
    msg = "Nested SaveVideo format objects must fail the API check."
    raise ValueError(msg)


def shipped_helios_prompt() -> dict[str, Json]:
    """Read the committed Helios Hello World API prompt."""
    slug = min(API_WORKFLOW_SLUGS)
    path = Path(__file__).resolve().parents[2] / "workflows" / "api" / f"{slug}.json"
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        msg = "The Helios API workflow must be a JSON object."
        raise TypeError(msg)
    prompt = loaded.get("prompt")
    if not isinstance(prompt, dict):
        msg = "The Helios API workflow must contain a prompt object."
        raise TypeError(msg)
    return cast("dict[str, Json]", prompt)


def require_flat_save_video(prompt: dict[str, Json]) -> None:
    """Require SaveVideo format keys in an API prompt to be strings."""
    require_flat_inputs(prompt)
    found = False
    for value in prompt.values():
        node = mapping_value(value)
        if str(node.get("class_type")) != "SaveVideo":
            continue
        found = True
        inputs = mapping_value(node["inputs"])
        format_value = inputs.get("format")
        codec = inputs.get("format.codec")
        if not isinstance(format_value, str) or not isinstance(codec, str):
            msg = "SaveVideo format and format.codec must be flat strings."
            raise TypeError(msg)
    if not found:
        msg = "The Helios API workflow must include SaveVideo."
        raise ValueError(msg)


def remember_api_prompt(
    generated: dict[Path, str],
    destination: Path,
    slug: str,
    workflow: dict[str, Json],
    schemas: dict[str, Json],
) -> None:
    """Convert one canvas graph and keep the API file for published examples."""
    document = api_document(workflow, schemas)
    if slug in API_WORKFLOW_SLUGS:
        generated[destination / "api" / f"{slug}.json"] = dump_document(document)
