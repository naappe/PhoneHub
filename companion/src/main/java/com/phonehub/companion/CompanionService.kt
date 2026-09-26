package com.phonehub.companion

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat

class CompanionService : Service() {
    companion object {
        private const val CHANNEL = "phonehub_connection"
        private const val NOTIFICATION_ID = 7001

        fun start(context: Context) {
            ContextCompat.startForegroundService(context, Intent(context, CompanionService::class.java))
        }
    }

    override fun onCreate() {
        super.onCreate()
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL, "PhoneHub connection", NotificationManager.IMPORTANCE_LOW)
        )
        val notification: Notification = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
            .setContentTitle("PhoneHub")
            .setContentText("Companion connection is active")
            .setOngoing(true)
            .setSilent(true)
            .build()
        startForeground(NOTIFICATION_ID, notification)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // Transport/pairing is added next. Keeping the service alive first lets
        // us validate Android/OxygenOS lifecycle behavior independently.
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
