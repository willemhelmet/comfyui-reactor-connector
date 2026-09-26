"""Expose one H3 Reference Turbo clip through native ComfyUI media sockets."""

import asyncio
from functools import partial
from ..language import translate
from ..media.output import owned_io
from ..media.images import encode_png
from comfy_api.latest import io, Input
from .controls import generation_controls
from ..errors import ErrorCode, ConnectorError
from ..execution.turbo import TurboGenerateOperation
from ...config.media.images import BATCH_IMAGE_DIMENSIONS
from ..state.generation.turbo import TurboGenerateRequest
from ..comfy.execution import generate_video, wait_for_execution, operation_fingerprint
from ...config.generation.turbo import (
    DEFAULT_ASPECT,
    OPTIONS_ASPECT,
    MAX_CLIP_SECONDS,
    MIN_CLIP_SECONDS,
    STEP_CLIP_SECONDS,
    DEFAULT_CLIP_SECONDS,
    MAX_REFERENCE_PIXELS,
    REFERENCE_SOCKET_COUNT,
    MAX_REFERENCE_ASPECT_RATIO,
    MIN_REFERENCE_ASPECT_RATIO,
)


class TurboGenerate(io.ComfyNode):
    """Generate one clip from a prompt and optional ordered reference images."""

    @classmethod
    async def fingerprint_inputs(cls, **_kwargs: object) -> str:
        """Include the operation revision and private configuration token in the cache key."""
        return await operation_fingerprint("h3-reference-turbo-recording-v1")

    @classmethod
    def define_schema(cls) -> io.Schema:
        """Define the inputs and outputs saved in ComfyUI workflows."""
        duration = io.Float.Input(
            "duration_seconds",
            display_name="video duration (seconds)",
            tooltip=(
                "H3 Reference Turbo chooses a supported clip length near this value. "
                "The clip must fit the video duration limit in Reactor settings."
            ),
            default=DEFAULT_CLIP_SECONDS,
            min=MIN_CLIP_SECONDS,
            max=MAX_CLIP_SECONDS,
            step=STEP_CLIP_SECONDS,
        )
        return io.Schema(
            node_id="ReactorIncH3ReferenceTurboGenerate",
            display_name="H3 Reference Turbo: Generate Video (Reactor)",
            category="Reactor/Generate",
            description="Generate a video clip with sound. Optional reference images guide the whole clip.",
            search_aliases=["Reactor", "H3 Reference Turbo", "Turbo", "reference", "audio"],
            inputs=[
                *generation_controls("turbo", duration=duration),
                io.Combo.Input("aspect", display_name="aspect ratio", options=OPTIONS_ASPECT, default=DEFAULT_ASPECT),
                *_reference_inputs(),
            ],
            outputs=[
                io.Video.Output(display_name="video"),
                io.Audio.Output(display_name="audio"),
                io.String.Output(display_name="recording details"),
            ],
        )

    @classmethod
    async def execute(  # pyright: ignore[reportIncompatibleMethodOverride] -- reason: ComfyUI calls by schema.  # noqa: PLR0913 -- reason: ComfyUI requires one named argument for each saved node input.
        cls,
        *,
        prompt: str,
        duration_seconds: float,
        seed: int,
        variation: int,
        aspect: str,
        image_1: Input.Image | None = None,
        image_2: Input.Image | None = None,
        image_3: Input.Image | None = None,
        image_4: Input.Image | None = None,
        image_5: Input.Image | None = None,
        image_6: Input.Image | None = None,
    ) -> io.NodeOutput:
        """Generate video with sound from a prompt and optional reference images."""
        # ComfyUI uses variation to invalidate its cache; Reactor does not consume it.
        del variation

        async def generate() -> io.NodeOutput:
            """Prepare reference images inside the owned task before starting the Reactor session."""
            references = await _encode_references(image_1, image_2, image_3, image_4, image_5, image_6)
            request = TurboGenerateRequest(prompt, duration_seconds, seed, aspect=aspect, references=references)
            return await generate_video(TurboGenerateOperation(request), node_id=cls.define_schema().node_id)

        return await wait_for_execution(asyncio.create_task(generate()))


def _reference_inputs() -> list[io.Input]:
    """Declare six optional reference sockets. The model accepts nine images."""
    return [
        io.Image.Input(
            f"image_{number}",
            display_name=f"reference image {number}",
            optional=True,
            tooltip=(
                "Optional reference for the whole clip. Connect Load Image from reference image 1 "
                "upward without skipping a socket. Picture 1 is reference image 1."
            ),
        )
        for number in range(1, REFERENCE_SOCKET_COUNT + 1)
    ]


async def _encode_references(*images: Input.Image | None) -> tuple[bytes | None, ...]:
    """Encode connected references and keep empty sockets in their original places."""
    encoded: list[bytes | None] = []
    for image in images:
        if image is None:
            encoded.append(None)
            continue
        _validate_reference_shape(image)
        encoded.append(await owned_io(partial(encode_png, image)))
    return tuple(encoded)


def _validate_reference_shape(image: Input.Image) -> None:
    """Reject a reference whose pixel count or aspect ratio the model will refuse."""
    if image.ndim != BATCH_IMAGE_DIMENSIONS or image.shape[0] != 1:
        return
    height = int(image.shape[1])
    width = int(image.shape[2])
    if height < 1 or width < 1 or height * width > MAX_REFERENCE_PIXELS:
        raise ConnectorError(ErrorCode.INVALID_INPUT, translate("main", "errors.turboReferencePixels"))
    aspect = width / height
    if not MIN_REFERENCE_ASPECT_RATIO <= aspect <= MAX_REFERENCE_ASPECT_RATIO:
        raise ConnectorError(ErrorCode.INVALID_INPUT, translate("main", "errors.turboReferenceAspect"))
