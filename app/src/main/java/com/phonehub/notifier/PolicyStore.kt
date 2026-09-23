package com.phonehub.notifier

import android.content.Context
import org.json.JSONObject

class PolicyStore(context: Context) {
    private val prefs = context.getSharedPreferences("phonehub_policies", Context.MODE_PRIVATE)

    fun get(packageName: String): AppPolicy {
        val raw = prefs.getString("app:$packageName", null) ?: return AppPolicy(packageName)
        return runCatching {
            val j = JSONObject(raw)
            AppPolicy(
                packageName = packageName,
                keepInstalled = j.optBoolean("keepInstalled", true),
                allowUsage = j.optBoolean("allowUsage", true),
                suspended = j.optBoolean("suspended", false),
                showNotifications = j.optBoolean("showNotifications", true),
                forwardNotifications = j.optBoolean("forwardNotifications", false),
                protectFromChanges = j.optBoolean("protectFromChanges", false),
                autoApplyOnSync = j.optBoolean("autoApplyOnSync", true),
            )
        }.getOrElse { AppPolicy(packageName) }
    }

    fun save(policy: AppPolicy) {
        val j = JSONObject()
            .put("keepInstalled", policy.keepInstalled)
            .put("allowUsage", policy.allowUsage)
            .put("suspended", policy.suspended)
            .put("showNotifications", policy.showNotifications)
            .put("forwardNotifications", policy.forwardNotifications)
            .put("protectFromChanges", policy.protectFromChanges)
            .put("autoApplyOnSync", policy.autoApplyOnSync)
        prefs.edit().putString("app:${policy.packageName}", j.toString()).apply()
    }

    fun allPackages(): List<String> = prefs.all.keys
        .filter { it.startsWith("app:") }
        .map { it.removePrefix("app:") }

    fun receiverUrl(): String = prefs.getString("receiver_url", "") ?: ""
    fun pairingToken(): String = prefs.getString("pairing_token", "") ?: ""
    fun saveConnection(url: String, token: String) = prefs.edit()
        .putString("receiver_url", url.trim())
        .putString("pairing_token", token.trim())
        .apply()

    fun globalForwarding(): Boolean = prefs.getBoolean("global_forwarding", true)
    fun setGlobalForwarding(enabled: Boolean) = prefs.edit().putBoolean("global_forwarding", enabled).apply()
    fun autoApply(): Boolean = prefs.getBoolean("auto_apply", true)
    fun setAutoApply(enabled: Boolean) = prefs.edit().putBoolean("auto_apply", enabled).apply()
    fun applyAtBoot(): Boolean = prefs.getBoolean("apply_at_boot", true)
    fun setApplyAtBoot(enabled: Boolean) = prefs.edit().putBoolean("apply_at_boot", enabled).apply()
}
