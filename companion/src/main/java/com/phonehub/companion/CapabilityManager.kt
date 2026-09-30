package com.phonehub.companion

import android.Manifest
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import androidx.core.content.ContextCompat
import org.json.JSONArray
import org.json.JSONObject

object CapabilityManager {
    fun cameraAllowed(context: Context): Boolean =
        ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED

    fun notificationsRuntimeAllowed(context: Context): Boolean =
        Build.VERSION.SDK_INT < 33 ||
            ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.POST_NOTIFICATIONS
            ) == PackageManager.PERMISSION_GRANTED

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
        CompanionService.isEnabled(context) &&
            cameraAllowed(context) &&
            notificationAccessAllowed(context) &&
            backgroundAllowed(context) &&
            PhoneHubScreenAccessService.isReady()

    fun missingRequired(context: Context): List<String> {
        val missing = mutableListOf<String>()
        if (!CompanionService.isEnabled(context)) missing.add("secure_connection")
        if (!cameraAllowed(context)) missing.add("remote_camera")
        if (!notificationAccessAllowed(context)) missing.add("notification_access")
        if (!backgroundAllowed(context)) missing.add("background_reconnect")
        if (!PhoneHubScreenAccessService.isReady()) missing.add("screen_access")
        return missing
    }

    fun json(context: Context): JSONObject {
        val missing = missingRequired(context)
        return JSONObject()
            .put("enrollment_complete", missing.isEmpty())
            .put("missing_required", JSONArray(missing))
            .put("secure_connection", CompanionService.isEnabled(context))
            .put("remote_camera", cameraAllowed(context))
            .put("notifications_permission", notificationsRuntimeAllowed(context))
            .put("notifications_permission_required", false)
            .put("notification_access", notificationAccessAllowed(context))
            .put("background_reconnect", backgroundAllowed(context))
            .put("boot_reconnect", true)
            .put("files", true)
            .put("app_inventory", true)
            .put("policy_bridge", true)
            .put("device_admin", deviceAdminActive(context))
            .put("device_owner", deviceOwner(context))
            .put("scrcpy_camera_available", true)
            .put("screen_capture_available", PhoneHubScreenAccessService.isReady())
            .put("screen_transport", "accessibility_snapshot")
            .put("screen_session_authorization_required", false)
            .put("usb_required_after_setup", false)
            .put("phone_role", "connection_policy_bridge")
    }
}
