package mv.phonehub.link

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat


enum class ServiceState(val notificationText: String) {
    ACTIVE("Active"),
    WAITING_FOR_NETWORK("Active - waiting for network"),
    WAITING_FOR_PAIRING("Active - waiting for paired PC"),
    CONNECTED("Active - paired PC connected"),
    ERROR("Active - connection error")
}

class PhoneHubService : Service() {
    private var phoneHubServer: PhoneHubServer? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> stopBackend()
            else -> startBackend()
        }
        return START_STICKY
    }

    override fun onDestroy() {
        phoneHubServer?.stop()
        phoneHubServer = null
        super.onDestroy()
    }

    private fun startBackend() {
        setEnabled(this, true)
        val pairingStore = PairingStore(applicationContext)
        val paired = pairingStore.getPairedClient() != null

        currentState = if (paired) ServiceState.ACTIVE else ServiceState.WAITING_FOR_PAIRING
        startForeground(NOTIFICATION_ID, buildNotification(currentState))

        if (phoneHubServer == null) {
            val router = CommandRouter(
                deviceInfoProvider = DeviceInfoController(applicationContext),
                screenRequestHandler = { ScreenRequestStore.markPending(applicationContext) },
                screenSharingProvider = { ScreenShareService.isSharing }
            )
            val processor = PhoneHubRequestProcessor(
                pairedClientProvider = { pairingStore.getPairedClient() },
                router = router,
                onAuthenticatedRequest = { setState(ServiceState.CONNECTED) }
            )
            phoneHubServer = PhoneHubServer(
                processor = processor,
                onServerError = { setState(ServiceState.ERROR) }
            ).also { it.start() }
        }
    }

    private fun stopBackend() {
        setEnabled(this, false)
        phoneHubServer?.stop()
        phoneHubServer = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    fun setState(state: ServiceState) {
        currentState = state
        val manager = getSystemService(NotificationManager::class.java)
        manager.notify(NOTIFICATION_ID, buildNotification(state))
    }

    private fun buildNotification(state: ServiceState) =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("PhoneHub")
            .setContentText(state.notificationText)
            .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .build()

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    "PhoneHub background service",
                    NotificationManager.IMPORTANCE_LOW
                ).apply {
                    description = "Keeps PhoneHub available to your paired PC"
                }
            )
        }
    }

    companion object {
        const val ACTION_START = "mv.phonehub.link.PHONEHUB_START"
        const val ACTION_STOP = "mv.phonehub.link.PHONEHUB_STOP"
        private const val CHANNEL_ID = "phonehub_core"
        private const val NOTIFICATION_ID = 8786
        private const val PREFS_NAME = "phonehub_core"
        private const val KEY_ENABLED = "enabled"

        @Volatile
        var currentState: ServiceState = ServiceState.ACTIVE
            private set

        fun isEnabled(context: Context): Boolean =
            context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .getBoolean(KEY_ENABLED, false)

        private fun setEnabled(context: Context, enabled: Boolean) {
            context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .edit()
                .putBoolean(KEY_ENABLED, enabled)
                .apply()
        }
    }
}
