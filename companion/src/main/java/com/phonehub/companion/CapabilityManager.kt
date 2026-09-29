package com.phonehub.companion

import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import org.json.JSONArray
import org.json.JSONObject

object CapabilityManager {

    fun notificationsRuntimeAllowed(context: Context): Boolean =
        Build.VERSION.SDK_INT < 33 ||
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    fun notificationAccessAllowed(context: Context): Boolean {
        return try {
            val enabled = Settings.Secure.getString(
                context.contentResolver,
                "enabled_notification_listeners"
            ) ?: ""
            enabled.contains(context.packageName, ignoreCase = true)
        } catch (_: Exception) {
            false
        }
    }

    fun backgroundAllowed(context: Context): Boolean {
        return try {
            val pm = context.getSystemService(PowerManager::class.java)
            pm.isIgnoringBatteryOptimizations(context.packageName)
        } catch (_: Exception) {
            false
        }
    }

    fun deviceAdminActive(context: Context): Boolean {
        return try {
            val dpm = context.getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
            dpm.isAdminActive(ComponentName(context, PhoneHubDeviceAdminReceiver::class.java))
        } catch (_: Exception) {
            false
        }
    }

    fun deviceOwner(context: Context): Boolean {
        return try {
            val dpm = context.getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
            dpm.isDeviceOwnerApp(context.packageName)
        } catch (_: Exception) {
            false
        }
    }

    fun requiredApprovalsComplete(context: Context): Boolean =
        CompanionService.isEnabled(context) &&            notificationsRuntimeAllowed(context) &&
            notificationAccessAllowed(context) &&
            backgroundAllowed(context)

    fun missingRequired(context: Context): List<String> {
        val missing = mutableListOf<String>()
        if (!CompanionService.isEnabled(context)) missing.add("secure_connection")
        if (!notificationsRuntimeAllowed(context)) missing.add("notifications_permission")
        if (!notificationAccessAllowed(context)) missing.add("notification_access")
        if (!backgroundAllowed(context)) missing.add("background_reconnect")
        return missing
    }

    fun json(context: Context): JSONObject {
        val missing = missingRequired(context)
        return JSONObject()
            .put("enrollment_complete", missing.isEmpty())
            .put("missing_required", JSONArray(missing))
            .put("secure_connection", CompanionService.isEnabled(context))
                        .put("notifications_permission", notificationsRuntimeAllowed(context))
            .put("notification_access", notificationAccessAllowed(context))
            .put("background_reconnect", backgroundAllowed(context))
            .put("boot_reconnect", true)
            .put("files", true)
            .put("app_inventory", true)
            .put("policy_bridge", true)
            .put("device_admin", deviceAdminActive(context))
            .put("device_owner", deviceOwner(context))
            .put("scrcpy_camera_available", true)
            .put("screen_capture_available", true)
            .put("screen_session_authorization_required", true)
            .put("usb_required_after_setup", false)
            .put("phone_role", "connection_policy_bridge")
    }
}
