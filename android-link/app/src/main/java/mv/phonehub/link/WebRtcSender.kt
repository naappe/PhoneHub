package mv.phonehub.link

import android.content.Context
import android.content.Intent
import android.media.projection.MediaProjection
import org.webrtc.DefaultVideoDecoderFactory
import org.webrtc.DefaultVideoEncoderFactory
import org.webrtc.EglBase
import org.webrtc.IceCandidate
import org.webrtc.MediaConstraints
import org.webrtc.PeerConnection
import org.webrtc.PeerConnectionFactory
import org.webrtc.ScreenCapturerAndroid
import org.webrtc.SdpObserver
import org.webrtc.SessionDescription
import org.webrtc.SurfaceTextureHelper
import org.webrtc.VideoSource
import org.webrtc.VideoTrack

class WebRtcSender(
    private val context: Context,
    private val projectionData: Intent,
    private val emitSignal: (SignalMessage) -> Unit,
    private val onStatus: (String) -> Unit,
    private val onProjectionStopped: () -> Unit
) {
    private val eglBase = EglBase.create()
    private lateinit var factory: PeerConnectionFactory
    private var peerConnection: PeerConnection? = null
    private var capturer: ScreenCapturerAndroid? = null
    private var surfaceTextureHelper: SurfaceTextureHelper? = null
    private var videoSource: VideoSource? = null
    private var videoTrack: VideoTrack? = null

    fun start() {
        PeerConnectionFactory.initialize(
            PeerConnectionFactory.InitializationOptions.builder(context)
                .setEnableInternalTracer(false)
                .createInitializationOptions()
        )

        factory = PeerConnectionFactory.builder()
            .setVideoEncoderFactory(DefaultVideoEncoderFactory(eglBase.eglBaseContext, true, true))
            .setVideoDecoderFactory(DefaultVideoDecoderFactory(eglBase.eglBaseContext))
            .createPeerConnectionFactory()

        val rtcConfig = PeerConnection.RTCConfiguration(
            listOf(
                PeerConnection.IceServer.builder("stun:stun.l.google.com:19302").createIceServer()
            )
        ).apply {
            sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
        }

        peerConnection = factory.createPeerConnection(rtcConfig, peerObserver())
            ?: error("Could not create WebRTC peer connection")

        capturer = ScreenCapturerAndroid(
            projectionData,
            object : MediaProjection.Callback() {
                override fun onStop() {
                    onProjectionStopped()
                }
            }
        )

        surfaceTextureHelper = SurfaceTextureHelper.create("PhoneHubCapture", eglBase.eglBaseContext)
        videoSource = factory.createVideoSource(true)
        capturer!!.initialize(surfaceTextureHelper, context, videoSource!!.capturerObserver)
        capturer!!.startCapture(720, 1280, 15)

        videoTrack = factory.createVideoTrack("PHONEHUB_SCREEN", videoSource).apply {
            setEnabled(true)
        }
        peerConnection!!.addTrack(videoTrack, listOf("phonehub-screen"))
        onStatus("Screen capture ready; waiting for viewer")
    }

    fun handleSignal(message: SignalMessage) {
        when (message.type) {
            "viewer-ready" -> createOffer()
            "answer" -> message.sdp?.let { setRemoteDescription(SessionDescription.Type.ANSWER, it) }
            "ice" -> {
                val candidate = message.candidate ?: return
                peerConnection?.addIceCandidate(
                    IceCandidate(message.sdpMid, message.sdpMLineIndex ?: 0, candidate)
                )
            }
            "stop" -> stop()
        }
    }

    private fun createOffer() {
        val pc = peerConnection ?: return
        pc.createOffer(object : SimpleSdpObserver() {
            override fun onCreateSuccess(description: SessionDescription) {
                pc.setLocalDescription(object : SimpleSdpObserver() {
                    override fun onSetSuccess() {
                        emitSignal(SignalMessage(type = "offer", sdp = description.description))
                        onStatus("Offer sent; connecting")
                    }
                }, description)
            }
        }, MediaConstraints())
    }

    private fun setRemoteDescription(type: SessionDescription.Type, sdp: String) {
        peerConnection?.setRemoteDescription(
            object : SimpleSdpObserver() {
                override fun onSetSuccess() {
                    onStatus("Viewer answer received")
                }
            },
            SessionDescription(type, sdp)
        )
    }

    private fun peerObserver() = object : PeerConnection.Observer {
        override fun onSignalingChange(newState: PeerConnection.SignalingState?) = Unit
        override fun onIceConnectionChange(newState: PeerConnection.IceConnectionState?) {
            when (newState) {
                PeerConnection.IceConnectionState.CONNECTED,
                PeerConnection.IceConnectionState.COMPLETED -> onStatus("Connected - live screen active")
                PeerConnection.IceConnectionState.FAILED -> onStatus("Connection failed - this network may require TURN")
                PeerConnection.IceConnectionState.DISCONNECTED -> onStatus("Viewer disconnected")
                else -> Unit
            }
        }
        override fun onIceConnectionReceivingChange(receiving: Boolean) = Unit
        override fun onIceGatheringChange(newState: PeerConnection.IceGatheringState?) = Unit
        override fun onIceCandidate(candidate: IceCandidate?) {
            if (candidate != null) {
                emitSignal(
                    SignalMessage(
                        type = "ice",
                        candidate = candidate.sdp,
                        sdpMid = candidate.sdpMid,
                        sdpMLineIndex = candidate.sdpMLineIndex
                    )
                )
            }
        }
        override fun onIceCandidatesRemoved(candidates: Array<out IceCandidate>?) = Unit
        override fun onAddStream(stream: org.webrtc.MediaStream?) = Unit
        override fun onRemoveStream(stream: org.webrtc.MediaStream?) = Unit
        override fun onDataChannel(dataChannel: org.webrtc.DataChannel?) = Unit
        override fun onRenegotiationNeeded() = Unit
        override fun onAddTrack(receiver: org.webrtc.RtpReceiver?, mediaStreams: Array<out org.webrtc.MediaStream>?) = Unit
    }

    fun stop() {
        try { capturer?.stopCapture() } catch (_: Exception) {}
        capturer?.dispose()
        surfaceTextureHelper?.dispose()
        videoTrack?.dispose()
        videoSource?.dispose()
        peerConnection?.close()
        peerConnection?.dispose()
        if (::factory.isInitialized) factory.dispose()
        eglBase.release()
        peerConnection = null
    }
}

open class SimpleSdpObserver : SdpObserver {
    override fun onCreateSuccess(description: SessionDescription?) = Unit
    override fun onSetSuccess() = Unit
    override fun onCreateFailure(error: String?) = Unit
    override fun onSetFailure(error: String?) = Unit
}
