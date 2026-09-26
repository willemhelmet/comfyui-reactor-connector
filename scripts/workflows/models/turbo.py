"""Describe H3 Reference Turbo workflow inputs and controls."""

from ..example import Example

EXAMPLES = (
    Example(
        "h3-reference-turbo-01-text-to-video",
        "ReactorIncH3ReferenceTurboGenerate",
        inputs={
            "prompt": "A small stream flows over smooth stones. Water splashes softly and birds call.",
            "duration_seconds": 6.0,
            "variation": 0,
            "seed": 42,
            "control_after_generate": "fixed",
            "aspect": "16:9",
        },
    ),
    Example(
        "h3-reference-turbo-02-reference-images",
        "ReactorIncH3ReferenceTurboGenerate",
        inputs={
            "prompt": (
                "The person in Picture 1 walks through the place in Picture 2 and carries the object in Picture 3. "
                "The camera follows from the side. Leaves rustle and birds call."
            ),
            "duration_seconds": 6.0,
            "variation": 0,
            "seed": 42,
            "control_after_generate": "fixed",
            "aspect": "16:9",
        },
        sources=("image_1", "image_2", "image_3"),
    ),
)
