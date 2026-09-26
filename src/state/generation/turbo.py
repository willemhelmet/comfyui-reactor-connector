"""H3 Reference Turbo request values."""

from .inputs import VideoInputs
from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class TurboGenerateRequest(VideoInputs):
    """An H3 Reference Turbo clip with ordered reference images.

    Attributes:
        aspect: Requested output aspect ratio.
        references: Encoded images in socket order. None keeps that socket empty.

    """

    aspect: str
    references: tuple[bytes | None, ...] = ()


__all__ = ["TurboGenerateRequest"]
