"""Validate queued clip replies and observe one clip's lifecycle."""

from __future__ import annotations

import json
import math
import asyncio
from uuid import UUID
from ...language import translate
from typing import cast, TYPE_CHECKING
from ...state.generation.fast import FastClip
from ...errors import ErrorCode, ConnectorError
from ....config.generation.fast import FRAME_RATE, MAX_CLIP_FRAMES, MAX_QUEUED_CLIPS, MAX_MEDIA_SECONDS

if TYPE_CHECKING:
    from ..events import SessionEvents


def read_clip(payload: dict[str, object], *, model: str = "Fast H3") -> FastClip:
    """Validate the clip identity, readiness, and agreement between duration and frame count."""
    raw = payload.get("clip")
    if not isinstance(raw, dict):
        raise ConnectorError(ErrorCode.UNAVAILABLE, translate("main", "errors.clipMissing", model=model))
    clip = cast("dict[str, object]", raw)
    identity, frames, ready = clip.get("clip_id"), clip.get("frames"), clip.get("ready")
    duration = seconds(clip.get("seconds"), model=model)
    if not isinstance(identity, str):
        raise ConnectorError(ErrorCode.UNAVAILABLE, translate("main", "errors.clipIdentifier", model=model))
    try:
        canonical = str(UUID(identity))
    except ValueError:
        raise ConnectorError(ErrorCode.UNAVAILABLE, translate("main", "errors.clipIdentifier", model=model)) from None
    if canonical != identity:
        raise ConnectorError(ErrorCode.UNAVAILABLE, translate("main", "errors.clipIdentifier", model=model))
    if (
        type(frames) not in (int, float)
        or not 1 <= cast("float", frames) <= MAX_CLIP_FRAMES
        or int(cast("float", frames)) != frames
        or type(ready) is not bool
        or not math.isclose(duration, cast("float", frames) / FRAME_RATE, abs_tol=0.001)
    ):
        raise ConnectorError(
            ErrorCode.UNAVAILABLE,
            translate("main", "errors.clipLength", model=model),
            diagnostic_detail=json.dumps(
                {
                    "frames_type": type(frames).__name__,
                    "frames": frames if type(frames) in (int, float) else None,
                    "seconds": duration,
                    "ready_type": type(ready).__name__,
                }
            ),
        )
    count = int(cast("float", frames))
    return FastClip(identity, count / FRAME_RATE, count, ready)


class FastClipEvents:
    """Limit stored clip updates; let the session remove the event handler."""

    def __init__(self, events: SessionEvents, *, limit: int = MAX_QUEUED_CLIPS, model: str = "Fast H3") -> None:
        """Subscribe to clip updates with a fixed maximum number of stored clips."""
        self.events = events
        self.limit = limit
        self.model = model
        self.finished_at: dict[str, float] = {}
        self.playback_changed = asyncio.Event()
        self.clips: dict[str, FastClip] = {}
        self.generated = asyncio.Event()
        self.finished = asyncio.Event()
        self.clip_id: str | None = None
        self.end_seconds: float | None = None
        events.transport.on("message", self.observe)
        events.handlers.append(("message", self.observe))

    def observe(self, message: object) -> None:
        """Record relevant clip updates and forward invalid replies to the session failure signal."""
        if not isinstance(message, dict):
            return
        envelope = cast("dict[str, object]", message)
        kind = envelope.get("type")
        if kind not in ("clip_generated", "clip_finished", "clip_failed", "clip_stopped"):
            return
        try:
            self._record_clip(envelope, str(kind))
        except ConnectorError as error:
            self.events.on_error(error)

    def _record_clip(self, envelope: dict[str, object], kind: str) -> None:
        """Validate a clip update and advance generation or playback signals."""
        if kind in ("clip_failed", "clip_stopped"):
            raise ConnectorError(ErrorCode.CAPTURE, translate("main", "errors.clipUnfinished", model=self.model))
        clip = read_clip(message_payload(envelope, str(kind), model=self.model), model=self.model)
        if len(self.clips) >= self.limit and clip.clip_id not in self.clips:
            raise ConnectorError(ErrorCode.UNAVAILABLE, translate("main", "errors.clipsUnexpected", model=self.model))
        self.clips[clip.clip_id] = clip
        if kind == "clip_generated":
            self.generated.set()
        else:
            finished = message_payload(envelope, "clip_finished", model=self.model)
            self.finished_at[clip.clip_id] = seconds(finished.get("seconds_sent"), model=self.model)
            self.playback_changed.set()
        if kind == "clip_finished" and clip.clip_id == self.clip_id:
            finished = message_payload(envelope, "clip_finished", model=self.model)
            self.end_seconds = seconds(finished.get("seconds_sent"), model=self.model)
            self.events.model_timing["finished_clips"] = self.events.model_timing.get("finished_clips", 0) + 1
            self.events.model_timing["last_clip_end_seconds"] = self.end_seconds
            self.finished.set()

    async def wait_ready(self, clip: FastClip) -> None:
        """Wait for generation without accepting changes to the queued clip length."""
        self.clip_id = clip.clip_id
        self.finished.clear()
        self.end_seconds = None
        expected = clip
        while not clip.ready:
            await self.generated.wait()
            self.generated.clear()
            clip = self.clips.get(clip.clip_id, clip)
            if clip.frames != expected.frames or clip.seconds != expected.seconds:
                raise ConnectorError(
                    ErrorCode.UNAVAILABLE,
                    translate("main", "errors.clipLengthChanged", model=self.model),
                )

    async def wait_finished(self, clip: FastClip) -> float:
        """Wait for playback and return its reported end time after checking the clip length."""
        while clip.clip_id not in self.finished_at:
            self.playback_changed.clear()
            await self.playback_changed.wait()
        reported = self.clips.get(clip.clip_id)
        if reported is None or reported.frames != clip.frames:
            raise ConnectorError(ErrorCode.CAPTURE, translate("main", "errors.acceptedClipChanged", model=self.model))
        return self.finished_at[clip.clip_id]


def message_payload(message: object, kind: str, *, model: str = "Fast H3") -> dict[str, object]:
    """Require a matching message type and an object payload."""
    if isinstance(message, dict):
        envelope = cast("dict[str, object]", message)
        payload = envelope.get("data")
        if envelope.get("type") == kind and isinstance(payload, dict):
            return cast("dict[str, object]", payload)
    raise ConnectorError(ErrorCode.UNAVAILABLE, translate("main", "errors.clipReply", model=model))


def seconds(value: object, *, model: str = "Fast H3") -> float:
    """Validate a provider media time before using it to select a recording interval."""
    if type(value) not in (int, float) or not 0 <= cast("float", value) <= MAX_MEDIA_SECONDS:
        raise ConnectorError(ErrorCode.UNAVAILABLE, translate("main", "errors.clipMediaTime", model=model))
    return float(cast("float", value))
