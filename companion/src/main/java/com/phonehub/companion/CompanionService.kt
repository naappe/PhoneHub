package com.phonehub.companion

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.provider.Settings
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.util.concurrent.atomic.AtomicBoolean

class CompanionService : Service() {
    companion object {
        private const val CHANNEL = "phonehub_connection"
        private const val NOTIFICATION_ID = 7001
        private const val PREFS = "phonehub"
        private const val ENABLED = "companion_enabled"
        private const val PORT = 47321

        fun enable(context: Context) {
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean(ENABLED, true).apply()
            start(context)
        }
        fun isEnabled(context: Context): Boolean =
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(ENABLED, false)
        fun start(context: Context) {
            ContextCompat.startForegroundService(context, Intent(context, CompanionService::class.java))
        }
    }

    private val running = AtomicBoolean(false)
    private var heartbeatThread: Thread? = null

    override fun onCreate() {
        super.onCreate()
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "PhoneHub connection", NotificationManager.IMPORTANCE_LOW))
        val notification: Notification = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
            .setContentTitle("PhoneHub")
            .setContentText("Companion service active")
            .setOngoing(true).setSilent(true).build()
        startForeground(NOTIFICATION_ID, notification)
        startHeartbeat()
    }

    private fun startHeartbeat() {
        if (!running.compareAndSet(false, true)) return
        heartbeatThread = Thread({
            DatagramSocket().use { socket ->
                socket.broadcast = true
                while (running.get()) {
                    try {
                        val id = Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID) ?: "android"
                        val payload = JSONObject()
                            .put("type", "heartbeat")
                            .put("version", 1)
                            .put("device_id", id)
                            .put("device_name", Build.MANUFACTURER + " " + Build.MODEL)
                            .put("timestamp", System.currentTimeMillis() / 1000)
                            .toString().toByteArray(Charsets.UTF_8)
                        val packet = DatagramPacket(payload, payload.size, InetAddress.getByName("255.255.255.255"), PORT)
                        socket.send(packet)
                    } catch (_: Exception) { }
                    try { Thread.sleep(5000) } catch (_: InterruptedException) { break }
                }
            }
        }, "phonehub-heartbeat").apply { isDaemon = true; start() }
    }

    override fun onDestroy() {
        running.set(false)
        heartbeatThread?.interrupt()
        super.onDestroy()
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startHeartbeat()
        return START_STICKY
    }
    override fun onBind(intent: Intent?): IBinder? = null
}
