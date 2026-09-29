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
    private val screenRequest = 8

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val title = TextView(this).apply {
            text = "PhoneHub Companion"
            textSize = 26f
            setPadding(48, 56, 48, 12)
        }

        val description = TextView(this).apply {
            text = "This phone is the secure Android bridge.\nAfter one-time setup, USB is not required. PhoneHub reconnects over Wi-Fi or mobile data and all management lives on your PC."
            textSize = 16f
            setPadding(48, 0, 48, 28)
        }

        status = TextView(this).apply {
            textSize = 18f
            setPadding(48, 12, 48, 24)
        }

        val enable = Button(this).apply {
            text = "Enable PhoneHub bridge"
            setOnClickListener { enableCompanion() }
        }

        val camera = Button(this).apply {
            text = "Allow camera permission"
            setOnClickListener {
                if (ContextCompat.checkSelfPermission(this@MainActivity, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                    ActivityCompat.requestPermissions(this@MainActivity, arrayOf(Manifest.permission.CAMERA), 9)
                } else {
                    updateStatus("Bridge enabled\nCamera permission already granted")
                }
            }
        }

        val notifications = Button(this).apply {
            text = "Open notification access"
            setOnClickListener {
                startActivity(Intent("android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS"))
            }
        }

        val screen = Button(this).apply {
            text = "Allow screen sharing"
            setOnClickListener {
                val manager = getSystemService(MediaProjectionManager::class.java)
                startActivityForResult(manager.createScreenCaptureIntent(), screenRequest)
            }
        }

        val stopScreen = Button(this).apply {
            text = "Stop screen sharing"
            setOnClickListener {
                ScreenCaptureService.stop(this@MainActivity)
                updateStatus("Connected bridge enabled\nScreen sharing stopped")
            }
        }

        val background = Button(this).apply {
            text = "Android background settings"
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
            addView(enable)
            addView(camera)
            addView(notifications)
            addView(screen)
            addView(stopScreen)
            addView(background)
        })

        if (CompanionService.isEnabled(this)) {
            CompanionService.start(this)
            updateStatus("Bridge enabled\nUSB not required - open PhoneHub on your PC")
        } else {
            updateStatus("One-time setup required\nTap Enable PhoneHub bridge")
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != screenRequest) return

        if (resultCode == RESULT_OK && data != null) {
            ScreenCaptureService.start(this, resultCode, data)
            updateStatus("Bridge enabled\nScreen sharing active - return to your PC")
        } else {
            updateStatus("Bridge enabled\nScreen sharing permission was not granted")
        }
    }

    private fun enableCompanion() {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(
                this,
                arrayOf(Manifest.permission.POST_NOTIFICATIONS),
                7
            )
        }

        CompanionService.enable(this)
        updateStatus("Bridge enabled\nUSB can be removed - PhoneHub will reconnect over the network")
    }

    private fun updateStatus(message: String) {
        status.text = message
    }
}
