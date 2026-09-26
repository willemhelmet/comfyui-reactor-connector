"""Add ordered reference images to a generated workflow."""

from ...src.language import translate
from ...src.state.documents import Json
from .serialize import build_node, build_input, build_output, native_widget_values
from .example import (
    Example,
    GENERATION_ID,
    EXTRA_INPUT_ID,
    THIRD_INPUT_ID,
    SOURCE_INPUT_ID,
)


def append_reference_images(
    example: Example, nodes: list[Json], links: list[Json], generation: dict[str, Json], native: dict[str, Json]
) -> None:
    """Add ordered reference images and connect them from picture 1 upward."""
    node_ids = (SOURCE_INPUT_ID, EXTRA_INPUT_ID, THIRD_INPUT_ID)
    sources = [source for source in example.sources if source.startswith("image_")]
    if len(sources) > len(node_ids):
        msg = "Reference workflows connect at most three images."
        raise ValueError(msg)
    incoming: list[Json] = []
    for source in sources:
        number = int(source.removeprefix("image_"))
        link_id = len(links) + 1
        image = build_node(
            node_ids[number - 1],
            "LoadImage",
            native_widget_values("LoadImage", native["LoadImage"]),
            title=translate("workflows", f"nodes.picture{number}"),
        )
        image["outputs"] = [build_output("IMAGE", "IMAGE", [link_id]), build_output("MASK", "MASK", [])]
        incoming.append(build_input(source, "IMAGE", link_id))
        links.append([link_id, node_ids[number - 1], 0, GENERATION_ID, len(incoming) - 1, "IMAGE"])
        nodes.append(image)
    generation["inputs"] = incoming
