# H3 Reference Turbo: Generate Video (Reactor)

Generate one video clip with audio. Reference images guide appearance for the whole
clip. They are not a fixed first or last frame. Connect **video** to **Save Video**
and **audio** to **Save Audio (Advanced)**.

The model name is `reactor/h3-reference-to-video-turbo-realtime`.

## Inputs

| Input                    | What to provide                                                                                                      |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| scene prompt             | Required scene and sound description, up to 8,000 characters.                                                        |
| video duration (seconds) | Requested clip length, from 5 to 15.084 seconds and within the video duration limit in Reactor settings. Default: 6. |
| seed                     | Integer from 0 to 4,294,967,295. Default: 42.                                                                        |
| run number               | Change this integer for another run. Default: 0.                                                                     |
| aspect ratio             | Canvas shape: 16:9, 1:1, 9:16, or 4:3. Default: 16:9.                                                                |
| reference image 1–6      | Optional images. Connect Load Image from reference image 1 upward, without skipping a socket.                        |

Each image must contain one RGB frame, at most 8192 pixels per side, at most 25
million pixels, and an aspect ratio from 1:4 to 4:1. It must also fit 25 MiB and
the upload limit in Reactor settings. The model accepts up to nine reference
images. This node connects six.

Picture 1 is reference image 1, Picture 2 is reference image 2, and so on. Name
those pictures in the prompt when you want the model to use a specific image.
Leave every reference socket empty to generate from the prompt alone.

H3 Reference Turbo chooses a supported duration near your request. Saved clips
use that accepted length, about 5.167 to 15.083 seconds. If that duration exceeds
the host limit, the connector ends the session before playback and reports an
error. Choose a shorter request with room below the limit.

## Run and save

This node runs without live controls. Saving requires one extra continuation,
which uses credits and is excluded from the output. It requests the deployment's
longest clip. The session ends once your selected recording is ready.

1. Set your key privately in **ComfyUI menu → Extensions → Reactor → Reactor settings**.
2. Open **h3-reference-turbo-01-text-to-video** or **h3-reference-turbo-02-reference-images** in native **Browse Templates → reactor-inc**.
3. Describe the scene, motion, and sound in **scene prompt**. Name Picture 1, Picture 2, and so on when images are connected.
4. Select **Run**. Wait for the clip to build, play, and become available for saving.
5. Play the saved video and separate sound output.

The saved result contains the selected clip without the idle video shown before
it. Video and sound use the same recording times to stay aligned. Native `VIDEO` contains
H.264 video and AAC sound; native `AUDIO` contains 48 kHz samples. AAC decoding
can include padding beyond the separate audio output's exact duration.

## Failures and cancellation

Building and recording readiness can
take longer than playback. The host session cap includes all those stages. If
the clip or recording is not ready in time, the node fails and removes partial
media. It does not retry an ambiguous queue or playback command.

Use ComfyUI's cancel control to end the session. Closing a tab or pausing
a preview does not cancel. Unchanged inputs can reuse ComfyUI's cache. Change
**run number** to run again. A seed cannot guarantee identical results after provider
model updates.

[H3 Reference Turbo schema](https://docs.reactor.inc/model-api-reference/h3-reference-to-video-turbo-realtime/schema)

For current session rates, open **Extensions → Reactor → Reactor models**.

## Recording details

This output describes the saved file and model. See the
field reference (**recording details** in the bundled `ADVANCED.md`) for timing, privacy, and cache behavior.
