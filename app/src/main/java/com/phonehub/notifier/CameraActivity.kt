package com.phonehub.notifier

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

class CameraActivity : Activity() {
    companion object { private const val REQ = 7101 }
    private var lens = "back"

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        lens = intent.getStringExtra("lens") ?: "back"
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED) {
            startCameraAndFinish()
        } else {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.CAMERA), REQ)
        }
    }

    private fun startCameraAndFinish() {
        val i = Intent(this, PhoneHubRemoteService::class.java).apply {
            action = PhoneHubRemoteService.ACTION_START_CAMERA
            putExtra(PhoneHubRemoteService.EXTRA_CAMERA_LENS, lens)
        }
        ContextCompat.startForegroundService(this, i)
        finish()
    }

    override fun onRequestPermissionsResult(
        requestCode: Int, permissions: Array<out String>, grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQ && grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
            startCameraAndFinish()
        } else {
            finish()
        }
    }
}
