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
    private val setupPermissionsRequest = 7
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
            text = "One-time secure setup. After setup, the phone reconnects automatically over Wi-Fi or mobile data. USB is not required for normal use."
            textSize = 16f
            setPadding(48, 0, 48, 28)
        }

        status = TextView(this).apply {
            textSize = 17f
            setPadding(48, 12, 48, 24)
        }

        setupButton = Button(this).apply {
            text = "Complete one-time setup"
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
        refreshSetupStatus()
    }

    override fun onResume() {
        super.onResume()

        if (waitingForNotificationAccess && notificationAccessGranted()) {
            waitingForNotificationAccess = false
            continueSetup()
            return
        }

        if (waitingForBatteryAccess && batteryBackgroundAllowed()) {
            waitingForBatteryAccess = false
            continueSetup()
            return
        }

        if (CompanionService.isEnabled(this)) CompanionService.start(this)
        refreshSetupStatus()
    }

    private fun beginSetup() {
        CompanionService.enable(this)

        val needed = mutableListOf<String>()
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            needed.add(Manifest.permission.CAMERA)
        }
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            needed.add(Manifest.permission.POST_NOTIFICATIONS)
        }

        if (needed.isNotEmpty()) {
            ActivityCompat.requestPermissions(this, needed.toTypedArray(), setupPermissionsRequest)
        } else {
            continueSetup()
        }
    }

    private fun continueSetup() {
        CompanionService.enable(this)

        if (!notificationAccessGranted()) {
            waitingForNotificationAccess = true
            refreshSetupStatus("Android approval required. Enable Samsung Secure notification access, then return.")
            startActivity(Intent("android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS"))
            return
        }

        if (!batteryBackgroundAllowed()) {
            waitingForBatteryAccess = true
            refreshSetupStatus("Android approval required. Allow Samsung Secure to run without battery restriction.")
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

        CompanionService.start(this)
        refreshSetupStatus("Setup complete. You can close this app and remove USB.")
    }

    private fun notificationAccessGranted(): Boolean {
        return try {
            val enabled = Settings.Secure.getString(contentResolver, "enabled_notification_listeners") ?: ""
            enabled.contains(packageName, ignoreCase = true)
        } catch (_: Exception) {
            PhoneHubNotificationListener.isRunning()
        }
    }

    private fun batteryBackgroundAllowed(): Boolean {
        return try {
            val pm = getSystemService(PowerManager::class.java)
            pm.isIgnoringBatteryOptimizations(packageName)
        } catch (_: Exception) {
            false
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == setupPermissionsRequest) continueSetup()
    }

    private fun refreshSetupStatus(extra: String? = null) {
        val bridge = CompanionService.isEnabled(this)
        val camera = ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        val notificationAccess = notificationAccessGranted()
        val background = batteryBackgroundAllowed()

        val complete = bridge && camera && notificationAccess && background
        setupButton.text = if (complete) "Setup complete" else "Complete one-time setup"
        setupButton.isEnabled = !complete

        status.text = when {
            complete -> "Ready\nBackground reconnect enabled\nUSB not required"
            !extra.isNullOrBlank() -> extra
            bridge -> "Setup is not complete yet. Tap below once to finish Android approvals."
            else -> "One-time setup required."
        }
    }
}
