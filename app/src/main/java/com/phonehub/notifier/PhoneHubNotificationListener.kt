package com.phonehub.notifier

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

class PhoneHubNotificationListener : NotificationListenerService() {
    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val store = PolicyStore(this)
        if (!store.globalForwarding()) return
        val policy = store.get(sbn.packageName)
        if (!policy.forwardNotifications) return
        val receiver = store.receiverUrl()
        if (receiver.isBlank()) return

        val extras = sbn.notification.extras
        val title = extras.getCharSequence("android.title")?.toString().orEmpty()
        val text = extras.getCharSequence("android.text")?.toString().orEmpty()
        val body = JSONObject()
            .put("package", sbn.packageName)
            .put("title", title)
            .put("text", text)
            .put("postedAt", sbn.postTime)
            .toString()

        thread(name = "PhoneHubForward") {
            runCatching {
                val c = URL(receiver).openConnection() as HttpURLConnection
                c.requestMethod = "POST"
                c.connectTimeout = 5000
                c.readTimeout = 5000
                c.doOutput = true
                c.setRequestProperty("Content-Type", "application/json")
                val token = store.pairingToken()
                if (token.isNotBlank()) c.setRequestProperty("Authorization", "Bearer $token")
                c.outputStream.use { it.write(body.toByteArray()) }
                c.inputStream.close()
                c.disconnect()
            }
        }
    }
}
