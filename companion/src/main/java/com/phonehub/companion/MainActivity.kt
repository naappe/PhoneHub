package com.phonehub.companion

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

class MainActivity : Activity() {
    private lateinit var status: TextView
    private lateinit var setupButton: Button

    private val runtimePermissionRequest = 7
    private var waitingForNotificationAccess = false
    private var waitingForBatteryAccess = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val title = TextView(this).apply {
            text = "Samsung Secure"
            textSize = 26f
            setPadding(48, 56, 48, 12)
        }

        val description = TextView(this).apply {
            text = "One-time phone enrollment for the secure PC connection and policy bridge. Approve the Android prompts once; normal control remains on the PC."
            textSize = 16f
            setPadding(48, 0, 48, 28)
        }

        status = TextView(this).apply {
            textSize = 17f
            setPadding(48, 12, 48, 24)
        }

        setupButton = Button(this).apply {
            text = "Allow all once"
            setOnClickListener { beginSetup() }
        }

        setContentView(LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 24, 32, 32)
            addView(title)
            addView(description)
            addView(status)
            addView(setupButton)
        })

        if (CompanionService.isEnabled(this)) CompanionService.start(this)
        refreshStatus()
    }

    override fun onResume() {
        super.onResume()

        if (waitingForNotificationAccess) {
            if (notificationAccessAllowed()) {
                waitingForNotificationAccess = false
                continueSetup()
                return
            }
            refreshStatus("Enable Samsung Secure notification access, then return here.")
            return
        }

        if (waitingForBatteryAccess) {
            if (backgroundAllowed()) {
                waitingForBatteryAccess = false
                finishSetup()
                return
            }
            refreshStatus("Allow background operation, then return here.")
            return
        }

        if (CompanionService.isEnabled(this)) CompanionService.start(this)
        refreshStatus()
    }

    private fun beginSetup() {
        CompanionService.enable(this)

        val missing = mutableListOf<String>()
        if (!CapabilityManager.cameraAllowed(this)) {
            missing.add(Manifest.permission.CAMERA)
        }
        if (!CapabilityManager.notificationsRuntimeAllowed(this)) {
            missing.add(Manifest.permission.POST_NOTIFICATIONS)
        }

        if (missing.isNotEmpty()) {
            refreshStatus("Approve the Android permission prompt(s). This is part of the one-time setup.")
            ActivityCompat.requestPermissions(this, missing.toTypedArray(), runtimePermissionRequest)
            return
        }

        continueSetup()
    }

    private fun continueSetup() {
        CompanionService.enable(this)

        if (!runtimePermissionsAllowed()) {
            refreshStatus("One-time setup is incomplete. Approve the remote camera and notification permissions once.")
            return
        }

        if (!notificationAccessAllowed()) {
            waitingForNotificationAccess = true
            refreshStatus("Next one-time approval: enable Samsung Secure notification access.")
            try {
                startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
            } catch (_: Exception) {
                startActivity(Intent("android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS"))
            }
            return
        }

        if (!backgroundAllowed()) {
            waitingForBatteryAccess = true
            refreshStatus("Final one-time approval: allow background operation so the secure connection can reconnect automatically.")
            try {
                startActivity(
                    Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                        data = Uri.parse("package:$packageName")
                    }
                )
            } catch (_: Exception) {
                startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
            }
            return
        }

        finishSetup()
    }

    private fun finishSetup() {
        CompanionService.enable(this)
        CompanionService.start(this)
        refreshStatus("Setup complete. You can close this app and use Samsung Secure on the PC.")
    }

    private fun runtimePermissionsAllowed(): Boolean =
        CapabilityManager.cameraAllowed(this) && CapabilityManager.notificationsRuntimeAllowed(this)

    private fun notificationAccessAllowed(): Boolean =
        CapabilityManager.notificationAccessAllowed(this)

    private fun backgroundAllowed(): Boolean =
        CapabilityManager.backgroundAllowed(this)

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != runtimePermissionRequest) return

        if (runtimePermissionsAllowed()) {
            continueSetup()
        } else {
            refreshStatus("Remote camera and notification permissions must be allowed to complete setup.")
        }
    }

    private fun refreshStatus(extra: String? = null) {
        val enabled = CompanionService.isEnabled(this)
        val camera = CapabilityManager.cameraAllowed(this)
        val notifications = CapabilityManager.notificationsRuntimeAllowed(this)
        val notificationAccess = CapabilityManager.notificationAccessAllowed(this)
        val background = CapabilityManager.backgroundAllowed(this)
        val complete = CapabilityManager.requiredApprovalsComplete(this)

        setupButton.text = if (complete) "All one-time approvals complete" else "Allow all once"
        setupButton.isEnabled = !complete

        val lines = mutableListOf<String>()
        lines.add(if (enabled) "Secure connection: ready" else "Secure connection: setup required")
        lines.add("Policy bridge: ready")
        lines.add(if (camera) "Remote camera: ready" else "Remote camera: one-time approval required")
        lines.add(if (notifications) "Notifications permission: allowed" else "Notifications permission: approval required")
        lines.add(if (notificationAccess) "Notification access: allowed" else "Notification access: approval required")
        lines.add(if (background) "Background reconnect: enabled" else "Background reconnect: approval required")
        if (complete) {
            lines.add("USB: not required")
            lines.add("Camera transport: scrcpy/ADB when reachable, encrypted WebRTC fallback on other networks.")
            lines.add("Screen transport: scrcpy/ADB when reachable, WebRTC/MediaProjection fallback when required.")
        }
        if (!extra.isNullOrBlank()) lines.add(extra)
        status.text = lines.joinToString("\n")
    }
}
