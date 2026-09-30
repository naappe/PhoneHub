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
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

class MainActivity : Activity() {
    private lateinit var status: TextView
    private lateinit var setupButton: Button
    private lateinit var screenButton: Button
    private lateinit var cameraButton: Button

    private val runtimePermissionRequest = 7
    private var waitingForNotificationAccess = false
    private var waitingForBatteryAccess = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val density = resources.displayMetrics.density
        fun dp(value: Int) = (value * density).toInt()
        fun rounded(fill: Int, radius: Int = 20) = GradientDrawable().apply {
            setColor(fill)
            cornerRadius = dp(radius).toFloat()
        }
        fun label(value: String, size: Float, color: Int, bold: Boolean = false) = TextView(this).apply {
            text = value
            textSize = size
            setTextColor(color)
            if (bold) setTypeface(typeface, android.graphics.Typeface.BOLD)
        }

        val page = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(24), dp(28), dp(24), dp(24))
            setBackgroundColor(Color.rgb(246, 248, 252))
        }

        val brand = label("SAMSUNG SECURE", 12f, Color.rgb(37, 99, 235), true).apply {
            letterSpacing = .12f
        }
        val title = label("Phone connection", 30f, Color.rgb(15, 23, 42), true).apply {
            setPadding(0, dp(8), 0, dp(4))
        }
        val description = label(
            "Secure bridge between this phone and your PC. Normal control stays on the PC.",
            15f, Color.rgb(71, 85, 105)
        ).apply { setPadding(0, 0, 0, dp(22)) }

        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(18), dp(20), dp(18))
            background = rounded(Color.WHITE)
            elevation = dp(2).toFloat()
        }
        val cardTitle = label("Connection health", 17f, Color.rgb(15, 23, 42), true)
        status = label("", 14f, Color.rgb(51, 65, 85)).apply {
            setPadding(0, dp(10), 0, 0)
            setLineSpacing(0f, 1.15f)
        }
        card.addView(cardTitle)
        card.addView(status)

        setupButton = Button(this).apply {
            text = "Complete setup"
            isAllCaps = false
            textSize = 15f
            setTextColor(Color.WHITE)
            background = rounded(Color.rgb(37, 99, 235), 14)
            setOnClickListener { beginSetup() }
        }

        val screenHint = label(
            "Remote screen\nSamsung Secure now uses Android Screen Access snapshots instead of casting or MediaProjection. Enable it once; there is no Start casting prompt for each session.",
            14f, Color.rgb(71, 85, 105)
        ).apply {
            setPadding(dp(18), dp(16), dp(18), dp(16))
            background = rounded(Color.rgb(238, 242, 255), 16)
        }
        screenButton = Button(this).apply {
            isAllCaps = false
            textSize = 15f
            setTextColor(Color.WHITE)
            background = rounded(Color.rgb(37, 99, 235), 14)
            setOnClickListener {
                if (PhoneHubScreenAccessService.isReady()) {
                    refreshStatus("Screen access is ready for the PC.")
                } else {
                    refreshStatus("Enable Samsung Secure Screen Access, then return here.")
                    startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
                }
            }
        }

        page.addView(brand)
        page.addView(title)
        page.addView(description)
        page.addView(card, LinearLayout.LayoutParams(-1, -2))
        page.addView(setupButton, LinearLayout.LayoutParams(-1, dp(52)).apply { topMargin = dp(16) })
        val cameraHint = label(
            "Remote camera\nAndroid 14 requires the camera service to be enabled while Samsung Secure is visible. Enable it once here; the PC can then open Front or Back camera remotely while the service remains active.",
            14f, Color.rgb(71, 85, 105)
        ).apply {
            setPadding(dp(18), dp(16), dp(18), dp(16))
            background = rounded(Color.rgb(240, 253, 244), 16)
        }
        cameraButton = Button(this).apply {
            isAllCaps = false
            textSize = 15f
            setTextColor(Color.WHITE)
            background = rounded(Color.rgb(37, 99, 235), 14)
            setOnClickListener {
                if (ContextCompat.checkSelfPermission(this@MainActivity, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                    requestPermissions(arrayOf(Manifest.permission.CAMERA), cameraPermissionRequest)
                } else {
                    try {
                        CameraWebRtcService.start(this@MainActivity, "back")
                        postDelayedCameraRefresh()
                        refreshStatus("Remote camera service is starting. Keep Samsung Secure visible for a moment.")
                    } catch (e: Exception) {
                        refreshStatus("Could not enable remote camera: " + (e.message ?: e.javaClass.simpleName))
                    }
                }
            }
        }

        page.addView(screenHint, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(16) })
        page.addView(screenButton, LinearLayout.LayoutParams(-1, dp(52)).apply { topMargin = dp(12) })
        page.addView(cameraHint, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(16) })
        page.addView(cameraButton, LinearLayout.LayoutParams(-1, dp(52)).apply { topMargin = dp(12) })
        setContentView(page)

        if (intent?.getBooleanExtra("pc_enroll", false) == true) {
            CompanionService.enable(this)
            CompanionService.start(this)
        } else if (CompanionService.isEnabled(this)) {
            CompanionService.start(this)
        }
        refreshStatus()
    }

    override fun onNewIntent(newIntent: Intent) {
        super.onNewIntent(newIntent)
        setIntent(newIntent)
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

    private fun postDelayedCameraRefresh() {
        android.os.Handler(mainLooper).postDelayed({ refreshStatus() }, 700)
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

        setupButton.text = if (complete) "Setup complete" else "Complete setup"
        setupButton.visibility = if (complete) View.GONE else View.VISIBLE
        val screenReady = PhoneHubScreenAccessService.isReady()
        screenButton.text = if (screenReady) "Screen access ready" else "Enable screen access"
        screenButton.isEnabled = !screenReady
        val cameraReady = CameraWebRtcService.isReady()
        cameraButton.text = if (cameraReady) "Remote camera ready" else "Enable remote camera"
        cameraButton.isEnabled = !cameraReady

        val lines = mutableListOf<String>()
        lines.add(if (enabled) "● Secure connection ready" else "○ Secure connection setup required")
        lines.add("● Policy bridge ready")
        lines.add(if (camera) "● Remote camera ready" else "○ Remote camera approval required")
        lines.add(if (notifications) "● Notifications allowed" else "○ Notifications approval required")
        lines.add(if (notificationAccess) "● Notification access allowed" else "○ Notification access required")
        lines.add(if (background) "● Background reconnect enabled" else "○ Background reconnect approval required")
        lines.add(if (screenReady) "● Screen access ready" else "○ Screen access not enabled")
        lines.add(if (cameraReady) "● Remote camera service ready" else "○ Remote camera service not enabled")
        if (complete) {
            lines.add("")
            lines.add("Internet relay ready • USB not required")
        }
        if (!extra.isNullOrBlank()) lines.add(extra)
        status.text = lines.joinToString("\n")
    }
}
