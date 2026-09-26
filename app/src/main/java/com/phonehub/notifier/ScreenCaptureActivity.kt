package com.phonehub.notifier

import android.app.Activity
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.os.Bundle

class ScreenCaptureActivity : Activity() {
    private lateinit var projectionManager: MediaProjectionManager

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        projectionManager = getSystemService(MediaProjectionManager::class.java)
        @Suppress("DEPRECATION")
        startActivityForResult(projectionManager.createScreenCaptureIntent(), 9001)
    }

    @Deprecated("Deprecated in Android SDK; retained for minSdk compatibility")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == 9001 && resultCode == RESULT_OK && data != null) {
            val service = Intent(this, PhoneHubRemoteService::class.java).apply {
                action = PhoneHubRemoteService.ACTION_START_CAPTURE
                putExtra(PhoneHubRemoteService.EXTRA_RESULT_CODE, resultCode)
                putExtra(PhoneHubRemoteService.EXTRA_RESULT_DATA, data)
            }
            startForegroundService(service)
        }
        finish()
    }
}