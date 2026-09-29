package com.phonehub.companion

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.CopyOnWriteArrayList

class PhoneHubNotificationListener : NotificationListenerService() {
    companion object {
        private val recent = CopyOnWriteArrayList<JSONObject>()

        fun snapshot(): JSONArray {
            val out = JSONArray()
            recent.takeLast(100).reversed().forEach { out.put(JSONObject(it.toString())) }
            return out
        }

        fun isRunning(): Boolean = running

        @Volatile
        private var running = false
    }

    override fun onListenerConnected() {
        running = true
        refreshActive()
    }

    override fun onListenerDisconnected() {
        running = false
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        if (sbn == null) return
        addNotification(sbn)
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification?) {
        if (sbn == null) return
        val id = sbn.key ?: return
        recent.removeAll { it.optString("key") == id }
    }

    private fun refreshActive() {
        try {
            activeNotifications?.forEach { addNotification(it) }
        } catch (_: Exception) {}
    }

    private fun addNotification(sbn: StatusBarNotification) {
        try {
            val extras = sbn.notification.extras
            val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty()
            val text = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString().orEmpty()
            val item = JSONObject()
                .put("key", sbn.key ?: "")
                .put("package", sbn.packageName ?: "")
                .put("title", title)
                .put("text", text)
                .put("posted_at", sbn.postTime)
                .put("ongoing", sbn.isOngoing)

            recent.removeAll { it.optString("key") == item.optString("key") }
            recent.add(item)
            while (recent.size > 100) recent.removeAt(0)
        } catch (_: Exception) {}
    }
}
