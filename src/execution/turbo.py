"""Queue and play one H3 Reference Turbo clip from ordered reference images."""

import json
from ..models import MODELS
from typing import ClassVar
from ..language import translate
from .transport import Transport
from .events import SessionEvents
from ..state.settings import Settings
from .inputs import VideoInputOperation
from ..state.session import RecordingWindow
from ..state.generation.fast import FastClip
from ..errors import ErrorCode, ConnectorError
from ..media.units import convert_mebibytes_to_bytes
from ..state.generation.turbo import TurboGenerateRequest
from .fast.clip import seconds, read_clip, FastClipEvents, message_payload
from ...config.generation.turbo import (
    OPTIONS_ASPECT,
    MAX_CLIP_SECONDS,
    MIN_CLIP_SECONDS,
    MAX_PROMPT_CHARACTERS,
    REFERENCE_SOCKET_COUNT,
    MAX_REFERENCE_MEBIBYTES,
)

_MODEL_KEY = "h3-reference-to-video-turbo-realtime"


class TurboGenerateOperation(VideoInputOperation[TurboGenerateRequest]):
    """Build and play a clip whose reference images guide the whole recording."""

    connection_name: ClassVar[str] = MODELS[_MODEL_KEY].connection_name
    model_title: ClassVar[str] = MODELS[_MODEL_KEY].title
    requires_audio: ClassVar[bool] = True

    def validate(self, settings: Settings) -> None:
        """Check the shared capture limits, then the Turbo clip and reference limits."""
        super().validate(settings)
        self._validate_clips(settings)

    def _validate_clips(self, settings: Settings) -> None:
        """Check prompt length, duration, aspect ratio, and ordered reference images."""
        if len(self.prompt) > MAX_PROMPT_CHARACTERS:
            raise ConnectorError(ErrorCode.INVALID_INPUT, translate("main", "errors.turboPromptLength"))
        if not MIN_CLIP_SECONDS <= self.duration_seconds <= MAX_CLIP_SECONDS:
            raise ConnectorError(ErrorCode.INVALID_INPUT, translate("main", "errors.turboDuration"))
        if self.inputs.aspect not in OPTIONS_ASPECT:
            raise ConnectorError(ErrorCode.INVALID_INPUT, translate("main", "errors.turboAspectRatio"))
        self._validate_references(settings)

    def _validate_references(self, settings: Settings) -> None:
        """Reject gaps, empty files, and images past the model or settings limit."""
        images = self.inputs.references
        if len(images) > REFERENCE_SOCKET_COUNT:
            raise ConnectorError(ErrorCode.INVALID_INPUT, translate("main", "errors.turboReferenceOrder"))
        limit = min(
            convert_mebibytes_to_bytes(settings.max_upload_megabytes),
            convert_mebibytes_to_bytes(MAX_REFERENCE_MEBIBYTES),
        )
        has_gap = False
        for image in images:
            if image is None:
                has_gap = True
                continue
            if has_gap:
                raise ConnectorError(ErrorCode.INVALID_INPUT, translate("main", "errors.turboReferenceOrder"))
            if type(image) is not bytes or not image or len(image) > limit:
                raise ConnectorError(ErrorCode.INVALID_INPUT, translate("main", "errors.turboReferenceUpload"))

    async def begin_generation(
        self, transport: Transport, events: SessionEvents, max_capture_seconds: float
    ) -> RecordingWindow:
        """Generate and play one clip, then close its recording with trailing media."""
        self._require_audio(transport)
        clips = FastClipEvents(events, model=self.model_title)
        await events.command_reply("set_autoplay", {"enabled": False})
        await events.command_reply("set_flush_on_clip_end", {"enabled": False})
        await events.command_reply("set_canvas", {"aspect": self.inputs.aspect})
        state = await self._state(transport, events)
        minimum = seconds(state.get("clip_seconds_min"), model=self.model_title)
        maximum = seconds(state.get("clip_seconds_max"), model=self.model_title)
        if not minimum <= self.duration_seconds <= maximum:
            raise ConnectorError(ErrorCode.INVALID_INPUT, translate("main", "errors.clipDurationRange"))
        clip = await self._queue_clip(transport, events, max_capture_seconds)
        await events.call("clip_build", clips.wait_ready(clip))
        start_seconds = await self._play_clip(transport, events, clips, clip)
        await self._queue_recording_tail(transport, events, clips, clip.clip_id, maximum)
        return RecordingWindow(start_seconds, clip.seconds)

    def _require_audio(self, transport: Transport) -> None:
        """Require the single received audio track used for the saved recording."""
        audio = [
            track
            for track in transport.tracks
            if track.name == "main_audio" and track.kind == "audio" and track.direction == "recvonly"
        ]
        if len(audio) != 1:
            raise ConnectorError(ErrorCode.UNAVAILABLE, translate("main", "errors.turboAudioMissing"))

    async def _queue_clip(self, transport: Transport, events: SessionEvents, max_capture_seconds: float) -> FastClip:
        """Upload connected reference images and queue one clip within the capture limit."""
        payload = await self._enqueue_payload(transport, events, self.duration_seconds)
        reply = await events.call("enqueue", transport.send_command("enqueue", payload))
        events.on_message(reply)
        events.check()
        clip = read_clip(message_payload(reply, "clip_queued", model=self.model_title), model=self.model_title)
        if clip.seconds > max_capture_seconds:
            raise ConnectorError(ErrorCode.INVALID_INPUT, translate("main", "errors.clipCaptureLimit"))
        return clip

    async def _enqueue_payload(self, transport: Transport, events: SessionEvents, duration: float) -> dict[str, object]:
        """Build an enqueue body that uses reference images, not frame endpoints."""
        payload: dict[str, object] = {"prompt": self.prompt, "seconds": duration, "seed": self.inputs.seed}
        uploaded: list[object] = []
        for index, image in enumerate(self._connected_references(), start=1):
            uploaded.append(
                await events.call(
                    "upload",
                    transport.upload_file(image, name=f"picture-{index}.png", mime_type="image/png"),
                )
            )
        if len(uploaded) == 1:
            payload["reference_image"] = uploaded[0]
        elif uploaded:
            payload["reference_images"] = uploaded
        return payload

    def _connected_references(self) -> tuple[bytes, ...]:
        """Return the leading connected images after validation has rejected gaps."""
        return tuple(image for image in self.inputs.references if image is not None)

    async def _play_clip(
        self, transport: Transport, events: SessionEvents, clips: FastClipEvents, clip: FastClip
    ) -> float:
        """Play the chosen clip and require a precise recording interval."""
        before = await self._state(transport, events)
        start = seconds(before.get("seconds_sent"), model=self.model_title)
        if before.get("playing") is not False:
            raise ConnectorError(ErrorCode.UNAVAILABLE, translate("main", "errors.turboPlaybackOrder"))
        await events.command_reply("play", {"clip_id": clip.clip_id})
        await events.call("clip_playback", clips.finished.wait())
        end = seconds(clips.end_seconds, model=self.model_title)
        if abs(end - start - clip.seconds) > 1 / self.fallback_fps:
            raise ConnectorError(
                ErrorCode.CAPTURE,
                translate("main", "errors.turboWindowMissing"),
                diagnostic_detail=json.dumps(
                    {"start_seconds": start, "end_seconds": end, "clip_seconds": clip.seconds}
                ),
            )
        events.model_timing.update(saved_start_seconds=start, saved_duration_seconds=clip.seconds)
        return start

    async def _queue_recording_tail(
        self,
        transport: Transport,
        events: SessionEvents,
        clips: FastClipEvents,
        clip_id: str,
        maximum: float,
    ) -> None:
        """Start one discarded continuation so the recorder can close the selected clip."""
        reply = await events.call(
            "recording_tail_queue",
            transport.send_command(
                "enqueue",
                {
                    "prompt": self.prompt,
                    "seconds": maximum,
                    "seed": self.inputs.seed,
                    "continue_from_clip_id": clip_id,
                },
            ),
        )
        events.on_message(reply)
        events.check()
        tail = read_clip(message_payload(reply, "clip_queued", model=self.model_title), model=self.model_title)
        if tail.seconds > maximum:
            raise ConnectorError(ErrorCode.UNAVAILABLE, translate("main", "errors.turboContinuationLength"))
        await events.call("recording_tail_build", clips.wait_ready(tail))
        await events.command_reply("play", {"clip_id": tail.clip_id})

    async def _state(self, transport: Transport, events: SessionEvents) -> dict[str, object]:
        """Fetch the model state and process any session failure before returning it."""
        reply = await events.call("get_state", transport.send_command("get_state", {}))
        events.on_message(reply)
        events.check()
        return message_payload(reply, "state_update", model=self.model_title)
