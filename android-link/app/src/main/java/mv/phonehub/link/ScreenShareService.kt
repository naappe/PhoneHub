package mv.phonehub.link

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

class ScreenShareService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var signaling: SignalingClient? = null
    private var sender: WebRtcSender? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> startSharing(intent)
            ACTION_STOP -> stopSharing()
        }
        return START_NOT_STICKY
    }

    @Suppress("DEPRECATION")
    private fun startSharing(intent: Intent) {
        val room = intent.getStringExtra(EXTRA_ROOM) ?: run {
            stopSelf()
            return
        }
        val projectionData = intent.getParcelableExtra<Intent>(EXTRA_PROJECTION_DATA) ?: run {
            stopSelf()
            return
        }

        createNotificationChannel()
        startForeground(
            NOTIFICATION_ID,
            NotificationCompat.Builder(this, CHANNEL_ID)
                .setContentTitle("PhoneHub")
                .setContentText("Sharing screen - room $room")
                .setSmallIcon(android.R.drawable.presence_video_online)
                .setOngoing(true)
                .build()
        )

        val signalClient = SignalingClient(
            scope = scope,
            roomCode = room,
            onSignal = { message -> sender?.handleSignal(message) },
            onStatus = { updateNotification(it) }
        )
        signaling = signalClient

        val webRtcSender = WebRtcSender(
            context = applicationContext,
            projectionData = projectionData,
            emitSignal = { message -> scope.launch { signaling?.send(message) } },
            onStatus = { updateNotification(it) },
            onProjectionStopped = { stopSharing() }
        )
        sender = webRtcSender

        try {
            webRtcSender.start()
            isSharing = true
            ScreenRequestStore.clear(applicationContext)
            scope.launch {
                try {
                    signalClient.connect()
                } catch (_: Exception) {
                    updateNotification("Signaling connection failed")
                }
            }
        } catch (_: Exception) {
            isSharing = false
            updateNotification("Could not start screen capture")
            stopSharing()
        }
    }

    private fun updateNotification(text: String) {
        val manager = getSystemService(NotificationManager::class.java)
        manager.notify(
            NOTIFICATION_ID,
            NotificationCompat.Builder(this, CHANNEL_ID)
                .setContentTitle("PhoneHub")
                .setContentText(text)
                .setSmallIcon(android.R.drawable.presence_video_online)
                .setOngoing(true)
                .build()
        )
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    "PhoneHub screen sharing",
                    NotificationManager.IMPORTANCE_LOW
                )
            )
        }
    }

    private fun stopSharing() {
        isSharing = false
        sender?.stop()
        sender = null
        scope.launch {
            try { signaling?.send(SignalMessage(type = "stop")) } catch (_: Exception) {}
            try { signaling?.close() } catch (_: Exception) {}
            signaling = null
        }
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        isSharing = false
        sender?.stop()
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        const val ACTION_START = "mv.phonehub.link.START"
        const val ACTION_STOP = "mv.phonehub.link.STOP"
        const val EXTRA_ROOM = "room"
        const val EXTRA_PROJECTION_DATA = "projection_data"
        private const val CHANNEL_ID = "phonehub_link_share"
        private const val NOTIFICATION_ID = 8787

        @Volatile
        var isSharing: Boolean = false
            private set
    }
}
