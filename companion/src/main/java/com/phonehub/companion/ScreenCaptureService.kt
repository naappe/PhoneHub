package com.phonehub.companion

import android.app.*
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.projection.MediaProjection
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import org.json.JSONObject
import org.webrtc.*
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class ScreenCaptureService : Service() {
    companion object {
        private const val TAG = "PhoneHubScreen"
        private const val CHANNEL = "phonehub_screen"
        private const val NOTIFICATION_ID = 7002
        private const val EXTRA_CODE = "projection_code"
        private const val EXTRA_DATA = "projection_data"

        @Volatile var active = false
        @Volatile var frameWidth = 0
        @Volatile var frameHeight = 0
        @Volatile var lastFrameAt = 0L
        @Volatile private var instance: ScreenCaptureService? = null

        fun start(context: Context, resultCode: Int, data: Intent) {
            val i = Intent(context, ScreenCaptureService::class.java)
                .putExtra(EXTRA_CODE, resultCode)
                .putExtra(EXTRA_DATA, data)
            context.startForegroundService(i)
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, ScreenCaptureService::class.java))
        }

        fun answerOffer(sdp: String): JSONObject {
            val service = instance
                ?: return JSONObject().put("type", "webrtc_error").put("message", "Screen sharing is not active on the phone.")
            return service.createWebRtcAnswer(sdp)
        }

        fun stopWebRtc() {
            instance?.closeWebRtc()
        }
    }

    private var projectionData: Intent? = null
    private var eglBase: EglBase? = null
    private var factory: PeerConnectionFactory? = null
    private var peer: PeerConnection? = null
    private var capturer: ScreenCapturerAndroid? = null
    private var source: VideoSource? = null
    private var track: VideoTrack? = null
    private var textureHelper: SurfaceTextureHelper? = null
    @Volatile private var iceComplete: CountDownLatch? = null
    @Volatile private var connectionState = "ready"

    override fun onCreate() {
        super.onCreate()
        instance = this
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL, "PhoneHub screen sharing", NotificationManager.IMPORTANCE_LOW)
        )
        val n = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_view)
            .setContentTitle("PhoneHub Screen")
            .setContentText("Ready for secure live screen streaming")
            .setOngoing(true)
            .setSilent(true)
            .build()
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTIFICATION_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        } else {
            startForeground(NOTIFICATION_ID, n)
        }
    }

    @Suppress("DEPRECATION")
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val code = intent?.getIntExtra(EXTRA_CODE, Activity.RESULT_CANCELED) ?: Activity.RESULT_CANCELED
        val data = intent?.getParcelableExtra<Intent>(EXTRA_DATA)
        if (code != Activity.RESULT_OK || data == null) {
            stopSelf()
            return START_NOT_STICKY
        }
        projectionData = Intent(data)
        val metrics = resources.displayMetrics
        val sourceW = metrics.widthPixels
        val sourceH = metrics.heightPixels
        val maxW = 720
        val scale = if (sourceW > maxW) maxW.toFloat() / sourceW else 1f
        frameWidth = (sourceW * scale).toInt().coerceAtLeast(1)
        frameHeight = (sourceH * scale).toInt().coerceAtLeast(1)
        active = true
        connectionState = "ready"
        return START_NOT_STICKY
    }

    @Synchronized
    private fun ensureFactory() {
        if (factory != null) return
        PeerConnectionFactory.initialize(
            PeerConnectionFactory.InitializationOptions.builder(applicationContext)
                .setEnableInternalTracer(false)
                .createInitializationOptions()
        )
        eglBase = EglBase.create()
        val encoder = DefaultVideoEncoderFactory(eglBase!!.eglBaseContext, true, true)
        val decoder = DefaultVideoDecoderFactory(eglBase!!.eglBaseContext)
        factory = PeerConnectionFactory.builder()
            .setVideoEncoderFactory(encoder)
            .setVideoDecoderFactory(decoder)
            .createPeerConnectionFactory()
    }

    @Synchronized
    private fun createWebRtcAnswer(offerSdp: String): JSONObject {
        if (!active || projectionData == null) {
            return JSONObject().put("type", "webrtc_error")
                .put("message", "Open PhoneHub Companion and tap Start screen sharing.")
        }
        if (offerSdp.isBlank()) {
            return JSONObject().put("type", "webrtc_error").put("message", "WebRTC offer is empty.")
        }

        return try {
            closeWebRtc()
            ensureFactory()
            connectionState = "negotiating"

            val iceServers = listOf(
                PeerConnection.IceServer.builder("stun:stun.l.google.com:19302").createIceServer(),
                PeerConnection.IceServer.builder("stun:stun1.l.google.com:19302").createIceServer()
            )
            val config = PeerConnection.RTCConfiguration(iceServers).apply {
                sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
                continualGatheringPolicy = PeerConnection.ContinualGatheringPolicy.GATHER_CONTINUALLY
            }

            val observer = object : PeerConnection.Observer {
                override fun onSignalingChange(state: PeerConnection.SignalingState) {}
                override fun onIceConnectionChange(state: PeerConnection.IceConnectionState) {
                    connectionState = "ice-" + state.name.lowercase()
                }
                override fun onIceConnectionReceivingChange(receiving: Boolean) {}
                override fun onIceGatheringChange(state: PeerConnection.IceGatheringState) {
                    if (state == PeerConnection.IceGatheringState.COMPLETE) iceComplete?.countDown()
                }
                override fun onIceCandidate(candidate: IceCandidate) {}
                override fun onIceCandidatesRemoved(candidates: Array<IceCandidate>) {}
                override fun onAddStream(stream: MediaStream) {}
                override fun onRemoveStream(stream: MediaStream) {}
                override fun onDataChannel(channel: DataChannel) {}
                override fun onRenegotiationNeeded() {}
                override fun onConnectionChange(state: PeerConnection.PeerConnectionState) {
                    connectionState = state.name.lowercase()
                }
            }

            peer = factory!!.createPeerConnection(config, observer)
                ?: return JSONObject().put("type", "webrtc_error").put("message", "Could not create Android WebRTC peer.")

            val remoteSet = SetObserver()
            peer!!.setRemoteDescription(
                remoteSet,
                SessionDescription(SessionDescription.Type.OFFER, offerSdp)
            )
            if (!remoteSet.await()) throw IllegalStateException(remoteSet.error ?: "Timed out setting WebRTC offer")

            val captureIntent = Intent(projectionData!!)
            capturer = ScreenCapturerAndroid(captureIntent, object : MediaProjection.Callback() {
                override fun onStop() {
                    active = false
                    connectionState = "projection-stopped"
                    closeWebRtc()
                }
            })
            source = factory!!.createVideoSource(true)
            source!!.adaptOutputFormat(frameWidth, frameHeight, 20)
            textureHelper = SurfaceTextureHelper.create("PhoneHub-WebRTC-Capture", eglBase!!.eglBaseContext)
            capturer!!.initialize(textureHelper, applicationContext, source!!.capturerObserver)
            capturer!!.startCapture(frameWidth, frameHeight, 20)
            track = factory!!.createVideoTrack("phonehub-screen", source!!)
            track!!.setEnabled(true)
            peer!!.addTrack(track, listOf("phonehub-screen"))

            val answerCreated = CreateObserver()
            peer!!.createAnswer(answerCreated, MediaConstraints())
            val answer = answerCreated.awaitDescription()
                ?: throw IllegalStateException(answerCreated.error ?: "Timed out creating WebRTC answer")

            val localSet = SetObserver()
            iceComplete = CountDownLatch(1)
            peer!!.setLocalDescription(localSet, answer)
            if (!localSet.await()) throw IllegalStateException(localSet.error ?: "Timed out setting WebRTC answer")
            if (peer!!.iceGatheringState() != PeerConnection.IceGatheringState.COMPLETE) {
                iceComplete?.await(12, TimeUnit.SECONDS)
            }

            val local = peer!!.localDescription
                ?: throw IllegalStateException("Android WebRTC answer was not available")
            lastFrameAt = System.currentTimeMillis()
            JSONObject()
                .put("type", "webrtc_answer")
                .put("sdp", local.description)
                .put("width", frameWidth)
                .put("height", frameHeight)
                .put("fps", 20)
                .put("state", connectionState)
        } catch (e: Exception) {
            Log.e(TAG, "WebRTC negotiation failed", e)
            closeWebRtc()
            JSONObject().put("type", "webrtc_error").put("message", e.message ?: e.javaClass.simpleName)
        }
    }

    @Synchronized
    fun closeWebRtc() {
        try { capturer?.stopCapture() } catch (_: Exception) {}
        try { capturer?.dispose() } catch (_: Exception) {}
        try { track?.dispose() } catch (_: Exception) {}
        try { source?.dispose() } catch (_: Exception) {}
        try { textureHelper?.dispose() } catch (_: Exception) {}
        try { peer?.close() } catch (_: Exception) {}
        try { peer?.dispose() } catch (_: Exception) {}
        capturer = null
        track = null
        source = null
        textureHelper = null
        peer = null
        iceComplete = null
        if (active) connectionState = "ready"
    }

    override fun onDestroy() {
        active = false
        projectionData = null
        closeWebRtc()
        try { factory?.dispose() } catch (_: Exception) {}
        try { eglBase?.release() } catch (_: Exception) {}
        factory = null
        eglBase = null
        instance = null
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private class SetObserver : SdpObserver {
        private val latch = CountDownLatch(1)
        @Volatile var error: String? = null
        override fun onSetSuccess() { latch.countDown() }
        override fun onSetFailure(message: String?) { error = message ?: "SDP set failed"; latch.countDown() }
        override fun onCreateSuccess(description: SessionDescription?) {}
        override fun onCreateFailure(message: String?) {}
        fun await(): Boolean {
            if (!latch.await(12, TimeUnit.SECONDS)) return false
            return error == null
        }
    }

    private class CreateObserver : SdpObserver {
        private val latch = CountDownLatch(1)
        @Volatile var description: SessionDescription? = null
        @Volatile var error: String? = null
        override fun onCreateSuccess(value: SessionDescription?) { description = value; latch.countDown() }
        override fun onCreateFailure(message: String?) { error = message ?: "SDP creation failed"; latch.countDown() }
        override fun onSetSuccess() {}
        override fun onSetFailure(message: String?) {}
        fun awaitDescription(): SessionDescription? {
            if (!latch.await(12, TimeUnit.SECONDS)) return null
            return description
        }
    }
}
