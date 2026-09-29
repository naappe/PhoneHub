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
    private val notificationPermissionRequest = 7
    private var waitingForBatteryAccess = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val title = TextView(this).apply {
            text = "Samsung Secure"
            textSize = 26f
            setPadding(48, 56, 48, 12)
        }

        val description = TextView(this).apply {
            text = "Secure connection and Android policy bridge only. All controls, files, camera, screen, notifications and automation are managed from the PC."
            textSize = 16f
            setPadding(48, 0, 48, 28)
        }

        status = TextView(this).apply {
            textSize = 17f
            setPadding(48, 12, 48, 24)
        }

        setupButton = Button(this).apply {
            text = "Complete one-time connection setup"
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

        if (waitingForBatteryAccess && backgroundAllowed()) {
            waitingForBatteryAccess = false
            CompanionService.start(this)
            refreshStatus("Setup complete. Close this app and use Samsung Secure on the PC.")
            return
        }

        if (CompanionService.isEnabled(this)) CompanionService.start(this)
        refreshStatus()
    }

    private fun beginSetup() {
        CompanionService.enable(this)

        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(
                this,
                arrayOf(Manifest.permission.POST_NOTIFICATIONS),
                notificationPermissionRequest
            )
            return
        }

        continueSetup()
    }

    private fun continueSetup() {
        CompanionService.enable(this)

        if (!backgroundAllowed()) {
            waitingForBatteryAccess = true
            refreshStatus("One Android approval remains: allow background operation so the secure connection can reconnect automatically.")
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
        refreshStatus("Setup complete. Close this app and use Samsung Secure on the PC.")
    }

    private fun backgroundAllowed(): Boolean {
        return try {
            val pm = getSystemService(PowerManager::class.java)
            pm.isIgnoringBatteryOptimizations(packageName)
        } catch (_: Exception) {
            false
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == notificationPermissionRequest) continueSetup()
    }

    private fun refreshStatus(extra: String? = null) {
        val enabled = CompanionService.isEnabled(this)
        val background = backgroundAllowed()
        val complete = enabled && background

        setupButton.text = if (complete) "Connection setup complete" else "Complete one-time connection setup"
        setupButton.isEnabled = !complete

        val lines = mutableListOf<String>()
        lines.add(if (enabled) "Secure connection: ready" else "Secure connection: setup required")
        lines.add("Policy bridge: ready")
        lines.add(if (background) "Background reconnect: enabled" else "Background reconnect: approval required")
        if (complete) lines.add("USB: not required")
        if (!extra.isNullOrBlank()) lines.add(extra)
        status.text = lines.joinToString("\n")
    }
}
