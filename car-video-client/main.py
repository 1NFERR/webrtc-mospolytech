from __future__ import annotations

import asyncio
import logging
import signal
from typing import Optional

from aiortc import (
    RTCIceCandidate,
    RTCPeerConnection,
    RTCSessionDescription,
    VideoStreamTrack,
)
from aiortc.sdp import candidate_from_sdp
from aiortc.rtcconfiguration import RTCConfiguration, RTCIceServer

from config import Settings, load_settings
from auth import KeycloakTokenProvider
from signaling import SignalingClient
from cams_video_track import CamsVideoStreamTrack
from video_track import StaticImageStreamTrack
from webcam_track import WebcamStreamTrack


class CarWebRTCSession:
    """Handles one WebRTC session at a time."""

    def __init__(self, settings: Settings, signaling: SignalingClient):
        self._settings = settings
        self._signaling = signaling
        self._pc: Optional[RTCPeerConnection] = None
        self._rtc_configuration: RTCConfiguration = self._build_rtc_configuration()
        self._video_track: Optional[VideoStreamTrack] = None

    def _build_rtc_configuration(self) -> RTCConfiguration:
        ice_servers = []
        for index, entry in enumerate(self._settings.ice_servers):
            if not isinstance(entry, dict):
                logging.warning("Skipping ICE server #%d with invalid format: %r", index, entry)
                continue
            try:
                ice_servers.append(RTCIceServer(**entry))
            except TypeError as exc:
                logging.warning(
                    "Skipping ICE server #%d due to invalid keys %s: %r",
                    index,
                    exc,
                    entry,
                )
        return RTCConfiguration(iceServers=ice_servers or None)

    async def handle_offer(self, payload: dict) -> None:
        logging.info("Received offer from operator")
        logging.info("Preparing peer connection for new session")
        await self._cleanup()

        self._pc = RTCPeerConnection(configuration=self._rtc_configuration)
        logging.debug(
            "Created RTCPeerConnection %s with ICE servers %s",
            id(self._pc),
            self._settings.ice_servers,
        )

        @self._pc.on("icecandidate")
        async def on_icecandidate(candidate: Optional[RTCIceCandidate]) -> None:
            if not candidate:
                return
            await self._signaling.send(
                {
                    "type": "candidate",
                    "clientId": self._settings.client_id,
                    "candidate": {
                        "candidate": candidate.to_sdp(),
                        "sdpMid": candidate.sdpMid,
                        "sdpMLineIndex": candidate.sdpMLineIndex,
                    },
                }
            )

        desc = RTCSessionDescription(sdp=payload["sdp"], type=payload["sdpType"])
        logging.debug("Applying remote description type=%s", desc.type)
        await self._pc.setRemoteDescription(desc)
        logging.debug("Remote description applied")

        logging.info(
            "Creating video track from source '%s'", self._settings.video_source
        )
        self._video_track = self._create_video_track()
        self._pc.addTrack(self._video_track)
        logging.debug("Video track added")

        for transceiver in self._pc.getTransceivers():
            if getattr(transceiver, "_offerDirection", None) is None:
                logging.debug(
                    "Defaulting missing offer direction to sendrecv for %s", transceiver.kind
                )
                transceiver._offerDirection = "sendrecv"

        logging.debug("Creating SDP answer")
        answer = await self._pc.createAnswer()
        await self._pc.setLocalDescription(answer)
        await self._signaling.send(
            {
                "type": "answer",
                "clientId": self._settings.client_id,
                "sdp": self._pc.localDescription.sdp,
                "sdpType": self._pc.localDescription.type,
            }
        )
        logging.info("Sent answer to operator")

    async def handle_remote_candidate(self, payload: dict) -> None:
        if not self._pc:
            logging.warning("No active peer connection for candidate: %s", payload)
            return
        candidate_payload = payload.get("candidate")
        if not candidate_payload:
            logging.info("Remote ICE gathering completed (no candidate payload)")
            return
        sdp = candidate_payload.get("candidate")
        if not sdp:
            logging.info("Remote ICE gathering completed")
            return
        try:
            rtc_candidate = candidate_from_sdp(sdp)
        except Exception:
            logging.exception(
                "Failed to parse remote candidate: %s", candidate_payload
            )
            return
        rtc_candidate.sdpMid = candidate_payload.get("sdpMid")
        rtc_candidate.sdpMLineIndex = candidate_payload.get("sdpMLineIndex")
        await self._pc.addIceCandidate(rtc_candidate)

    async def handle_operator_disconnected(self, _payload: dict) -> None:
        logging.info("Operator detached, cleaning up current peer connection")
        await self._cleanup()

    async def stop(self) -> None:
        await self._cleanup()

    async def _cleanup(self) -> None:
        if self._pc:
            logging.info("Closing previous peer connection")
            await self._pc.close()
            self._pc = None
            await self._signaling.send({"type": "release"})
        if self._video_track:
            await self._video_track.stop()
            self._video_track = None

    def _create_video_track(self) -> VideoStreamTrack:
        source = self._settings.video_source.lower()
        if source == "webcam":
            return WebcamStreamTrack(
                camera_index=0,
                fps=30,
                width=1280,
                height=720,
            )
        if source == "cams_video":
            return CamsVideoStreamTrack(
                folder=self._settings.cams_video_folder,
                filename=self._settings.cams_video_filename,
            )
        if source == "static_image":
            return StaticImageStreamTrack(self._settings.image_path)

        logging.warning(
            "Unknown video_source '%s', falling back to static image",
            self._settings.video_source,
        )
        return StaticImageStreamTrack(self._settings.image_path)


async def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    token_provider = KeycloakTokenProvider(settings)
    signaling = SignalingClient(settings, token_provider)
    session = CarWebRTCSession(settings, signaling)

    signaling.on("offer", session.handle_offer)
    signaling.on("candidate", session.handle_remote_candidate)
    signaling.on("operator-disconnected", session.handle_operator_disconnected)

    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    client_task = asyncio.create_task(signaling.start())

    await stop_event.wait()
    logging.info("Shutting down car video client")
    await signaling.stop()
    await session.stop()
    await client_task


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
