package com.phonehub.notifier

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.widget.Toast

class PackageInstallReceiver : BroadcastReceiver() {
    companion object {
        const val ACTION_INSTALL_RESULT = "com.phonehub.notifier.INSTALL_RESULT"
    }

    override fun onReceive(context: Context, intent: Intent) {
        val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)
        val message = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE).orEmpty()

        when (status) {
            PackageInstaller.STATUS_SUCCESS -> {
                Toast.makeText(context, "Tailscale installed successfully", Toast.LENGTH_LONG).show()
                val launch = context.packageManager.getLaunchIntentForPackage(TailscaleInstaller.PACKAGE)
                if (launch != null) {
                    launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    context.startActivity(launch)
                }
            }
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                val confirm = intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
                if (confirm != null) {
                    confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    context.startActivity(confirm)
                }
            }
            else -> {
                Toast.makeText(
                    context,
                    if (message.isBlank()) "Tailscale install failed" else "Install failed: " + message,
                    Toast.LENGTH_LONG
                ).show()
            }
        }
    }
}
