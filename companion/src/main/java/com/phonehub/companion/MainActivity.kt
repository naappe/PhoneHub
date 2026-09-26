package com.phonehub.companion

import android.Manifest
import android.app.Activity
import android.media.projection.MediaProjectionManager
import android.content.Intent
import android.content.pm.PackageManager
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
        status = TextView(this).apply {
            textSize = 20f
            setPadding(48, 64, 48, 32)
        }
        val start = Button(this).apply {
            text = "Enable automatic service"
            setOnClickListener { enableCompanion() }
        }
        val screen = Button(this).apply {
            text = "Start screen sharing"
            setOnClickListener {
                val m = getSystemService(MediaProjectionManager::class.java)
                startActivityForResult(m.createScreenCaptureIntent(), screenRequest)
            }
        }
        val stopScreen = Button(this).apply {
            text = "Stop screen sharing"
            setOnClickListener {
                ScreenCaptureService.stop(this@MainActivity)
                status.text = "PhoneHub Companion\n\nScreen sharing stopped."
            }
        }
        val battery = Button(this).apply {
            text = "Background settings"
            setOnClickListener { startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)) }
        }
        setContentView(LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 32, 32, 32)
            addView(status)
            addView(start)
            addView(screen)
            addView(stopScreen)
            addView(battery)
        })
        if (CompanionService.isEnabled(this)) {
            CompanionService.start(this)
            status.text = "PhoneHub Companion\n\nAutomatic service is enabled."
        } else {
            status.text = "PhoneHub Companion\n\nReady for one-time enrollment."
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == screenRequest) {
            if (resultCode == RESULT_OK && data != null) {
                ScreenCaptureService.start(this, resultCode, data)
                status.text = "PhoneHub Companion\n\nScreen sharing active. You can return to the PC."
            } else {
                status.text = "PhoneHub Companion\n\nScreen sharing permission was not granted."
            }
        }
    }

    private fun enableCompanion() {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 7)
        }
        CompanionService.enable(this)
        status.text = "PhoneHub Companion\n\nAutomatic service is enabled."
    }
}
