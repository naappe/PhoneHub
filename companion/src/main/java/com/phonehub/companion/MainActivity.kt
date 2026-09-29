package com.phonehub.companion

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
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
    private val screenRequest = 8
    private var waitingForNotificationAccess = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val title = TextView(this).apply {
            text = "PhoneHub Companion"
            textSize = 26f
            setPadding(48, 56, 48, 12)
        }

        val description = TextView(this).apply {
            text = "One-time Android setup only. After setup, USB is not required. PhoneHub reconnects over Wi-Fi or mobile data and management stays on your PC."
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

        val screen = Button(this).apply {
            text = "Start screen sharing when needed"
            setOnClickListener {
                val manager = getSystemService(MediaProjectionManager::class.java)
                startActivityForResult(manager.createScreenCaptureIntent(), screenRequest)
            }
        }

        val stopScreen = Button(this).apply {
            text = "Stop screen sharing"
            setOnClickListener {
                ScreenCaptureService.stop(this@MainActivity)
                refreshSetupStatus("Screen sharing stopped")
            }
        }

        val background = Button(this).apply {
            text = "Optional: background / battery settings"
            setOnClickListener {
                startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
            }
        }

        setContentView(LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 24, 32, 32)
            addView(title)
            addView(description)
            addView(status)
            addView(setupButton)
            addView(screen)
            addView(stopScreen)
            addView(background)
        })

        if (CompanionService.isEnabled(this)) CompanionService.start(this)
        refreshSetupStatus()
    }

    override fun onResume() {
        super.onResume()
        if (waitingForNotificationAccess && notificationAccessGranted()) {
            waitingForNotificationAccess = false
            refreshSetupStatus("Notification access enabled")
        } else {
            refreshSetupStatus()
        }
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
            refreshSetupStatus("One remaining Android approval: enable PhoneHub notification access, then return here")
            startActivity(Intent("android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS"))
            return
        }
        refreshSetupStatus("Setup complete - USB can be removed")
    }

    private fun notificationAccessGranted(): Boolean {
        return try {
            val enabled = Settings.Secure.getString(contentResolver, "enabled_notification_listeners") ?: ""
            enabled.contains(packageName, ignoreCase = true)
        } catch (_: Exception) {
            PhoneHubNotificationListener.isRunning()
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == setupPermissionsRequest) continueSetup()
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != screenRequest) return

        if (resultCode == RESULT_OK && data != null) {
            ScreenCaptureService.start(this, resultCode, data)
            refreshSetupStatus("Screen sharing active - return to your PC")
        } else {
            refreshSetupStatus("Screen sharing was not started")
        }
    }

    private fun refreshSetupStatus(extra: String? = null) {
        val bridge = CompanionService.isEnabled(this)
        val camera = ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        val notifications = notificationAccessGranted()
        val postNotifications = Build.VERSION.SDK_INT < 33 ||
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

        val complete = bridge && camera && notifications
        setupButton.text = if (complete) "Setup complete" else "Complete one-time setup"
        setupButton.isEnabled = !complete

        val lines = mutableListOf<String>()
        lines.add(if (bridge) "Bridge: ready" else "Bridge: setup required")
        lines.add(if (camera) "Camera: allowed" else "Camera: permission required")
        lines.add(if (notifications) "Notification access: allowed" else "Notification access: required")
        if (!postNotifications) lines.add("PhoneHub alerts: permission not granted")
        if (complete) lines.add("USB: not required after setup")
        if (!extra.isNullOrBlank()) lines.add(extra)
        status.text = lines.joinToString("\n")
    }
}
