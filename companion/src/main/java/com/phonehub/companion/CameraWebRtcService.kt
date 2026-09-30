package com.phonehub.companion

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import org.json.JSONObject
import org.webrtc.*
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class CameraWebRtcService : Service() {
    companion object {
        private const val TAG = "PhoneHubCamera"
        private const val CHANNEL = "phonehub_camera"
        private const val NOTIFICATION_ID = 7003
        private const val ACTION_START = "com.phonehub.companion.CAMERA_WEBRTC_START"
        private const val ACTION_STOP = "com.phonehub.companion.CAMERA_WEBRTC_STOP"
        private const val EXTRA_LENS = "lens"

        @Volatile var active = false
        @Volatile var lens = "back"
        @Volatile private var instance: CameraWebRtcService? = null

        fun start(context: Context, requestedLens: String) {
            val intent = Intent(context, CameraWebRtcService::class.java)
                .setAction(ACTION_START)
                .putExtra(EXTRA_LENS, requestedLens)
            ContextCompat.startForegroundService(context, intent)
        }

        fun stop(context: Context) {
            context.startService(
                Intent(context, CameraWebRtcService::class.java).setAction(ACTION_STOP)
            )
        }

        fun isReady(): Boolean = instance != null && active

        fun startAndAnswer(context: Context, requestedLens: String, sdp: String): JSONObject {
            // Android 14+ does not allow a camera foreground service to be
            // created silently from the background. If the user enabled the
            // service from Samsung Secure while the activity was visible, reuse it.
            val ready = instance
            if (ready != null && active) {
                lens = if (requestedLens == "front") "front" else "back"
                return ready.createWebRtcAnswer(sdp)
            }
            try {
                start(context, requestedLens)
            } catch (e: Exception) {
                return JSONObject().put("type", "camera_webrtc_error")
                    .put("message", "Remote camera is not enabled. Open Samsung Secure on the phone and tap Enable remote camera.")
            }
            val deadline = System.currentTimeMillis() + 2500
            while (System.currentTimeMillis() < deadline) {
                val service = instance
                if (service != null && active) return service.createWebRtcAnswer(sdp)
                try { Thread.sleep(50) } catch (_: InterruptedException) { break }
            }
            return JSONObject().put("type", "camera_webrtc_error")
                .put("message", "Remote camera is not enabled. Open Samsung Secure on the phone and tap Enable remote camera.")
        }

        fun stopWebRtc() {
            instance?.closeWebRtc()
        }
    }

    private var eglBase: EglBase? = null
    private var factory: PeerConnectionFactory? = null
    private var peer: PeerConnection? = null
    private var capturer: VideoCapturer? = null
    private var source: VideoSource? = null
    private var track: VideoTrack? = null
    private var textureHelper: SurfaceTextureHelper? = null
    @Volatile private var iceComplete: CountDownLatch? = null

    override fun onCreate() {
        super.onCreate()
        instance = this
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL, "Samsung Secure camera", NotificationManager.IMPORTANCE_LOW)
        )
        val notification = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setContentTitle("Samsung Secure Camera")
            .setContentText("Secure remote camera available")
            .setOngoing(true)
            .setSilent(true)
            .build()
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                active = false
                closeWebRtc()
                stopSelf()
                return START_NOT_STICKY
            }
            ACTION_START -> {
                lens = if (intent.getStringExtra(EXTRA_LENS) == "front") "front" else "back"
                active = ContextCompat.checkSelfPermission(
                    this,
                    Manifest.permission.CAMERA
                ) == PackageManager.PERMISSION_GRANTED
            }
        }
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
        factory = PeerConnectionFactory.builder()
            .setVideoEncoderFactory(DefaultVideoEncoderFactory(eglBase!!.eglBaseContext, true, true))
            .setVideoDecoderFactory(DefaultVideoDecoderFactory(eglBase!!.eglBaseContext))
            .createPeerConnectionFactory()
    }

    private fun createCameraCapturer(): VideoCapturer? {
        val enumerator = Camera2Enumerator(this)
        val names = enumerator.deviceNames
        val preferred = if (lens == "front") {
            names.firstOrNull { enumerator.isFrontFacing(it) }
        } else {
            names.firstOrNull { enumerator.isBackFacing(it) }
        }
        val name = preferred ?: names.firstOrNull() ?: return null
        return enumerator.createCapturer(name, null)
    }

    @Synchronized
    private fun createWebRtcAnswer(offerSdp: String): JSONObject {
        if (!active) {
            return JSONObject().put("type", "camera_webrtc_error")
                .put("message", "Remote camera permission is not available.")
        }
        if (offerSdp.isBlank()) {
            return JSONObject().put("type", "camera_webrtc_error")
                .put("message", "WebRTC offer is empty.")
        }

        return try {
            closeWebRtc()
            ensureFactory()

            val config = PeerConnection.RTCConfiguration(
                listOf(
                    PeerConnection.IceServer.builder("stun:stun.l.google.com:19302").createIceServer(),
                    PeerConnection.IceServer.builder("stun:stun1.l.google.com:19302").createIceServer()
                )
            ).apply {
                sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
                continualGatheringPolicy = PeerConnection.ContinualGatheringPolicy.GATHER_CONTINUALLY
            }

            val observer = object : PeerConnection.Observer {
                override fun onSignalingChange(state: PeerConnection.SignalingState) {}
                override fun onIceConnectionChange(state: PeerConnection.IceConnectionState) {}
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
                override fun onConnectionChange(state: PeerConnection.PeerConnectionState) {}
            }

            peer = factory!!.createPeerConnection(config, observer)
                ?: throw IllegalStateException("Could not create Android WebRTC peer")

            val remoteSet = SetObserver()
            peer!!.setRemoteDescription(
                remoteSet,
                SessionDescription(SessionDescription.Type.OFFER, offerSdp)
            )
            if (!remoteSet.await()) throw IllegalStateException(remoteSet.error ?: "Could not set offer")

            capturer = createCameraCapturer()
                ?: throw IllegalStateException("No Android camera was found")
            source = factory!!.createVideoSource(false)
            textureHelper = SurfaceTextureHelper.create(
                "PhoneHub-Camera-WebRTC",
                eglBase!!.eglBaseContext
            )
            capturer!!.initialize(textureHelper, applicationContext, source!!.capturerObserver)
            capturer!!.startCapture(1280, 720, 24)

            track = factory!!.createVideoTrack("phonehub-camera", source!!)
            track!!.setEnabled(true)
            peer!!.addTrack(track, listOf("phonehub-camera"))

            val created = CreateObserver()
            peer!!.createAnswer(created, MediaConstraints())
            val answer = created.awaitDescription()
                ?: throw IllegalStateException(created.error ?: "Could not create answer")

            val localSet = SetObserver()
            iceComplete = CountDownLatch(1)
            peer!!.setLocalDescription(localSet, answer)
            if (!localSet.await()) throw IllegalStateException(localSet.error ?: "Could not set answer")
            if (peer!!.iceGatheringState() != PeerConnection.IceGatheringState.COMPLETE) {
                iceComplete?.await(12, TimeUnit.SECONDS)
            }

            val local = peer!!.localDescription
                ?: throw IllegalStateException("WebRTC answer unavailable")

            JSONObject()
                .put("type", "camera_webrtc_answer")
                .put("sdp", local.description)
                .put("lens", lens)
                .put("width", 1280)
                .put("height", 720)
                .put("fps", 24)
        } catch (e: Exception) {
            Log.e(TAG, "Camera WebRTC negotiation failed", e)
            closeWebRtc()
            JSONObject().put("type", "camera_webrtc_error")
                .put("message", e.message ?: e.javaClass.simpleName)
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
    }

    override fun onDestroy() {
        active = false
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
        fun await(): Boolean = latch.await(12, TimeUnit.SECONDS) && error == null
    }

    private class CreateObserver : SdpObserver {
        private val latch = CountDownLatch(1)
        @Volatile var description: SessionDescription? = null
        @Volatile var error: String? = null
        override fun onCreateSuccess(value: SessionDescription?) { description = value; latch.countDown() }
        override fun onCreateFailure(message: String?) { error = message ?: "SDP create failed"; latch.countDown() }
        override fun onSetSuccess() {}
        override fun onSetFailure(message: String?) {}
        fun awaitDescription(): SessionDescription? {
            if (!latch.await(12, TimeUnit.SECONDS)) return null
            return description
        }
    }
}
