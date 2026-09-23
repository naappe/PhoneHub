package com.phonehub.notifier

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.os.Build
import android.os.Handler
import android.os.Looper
import java.io.BufferedInputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import kotlin.concurrent.thread

data class InstallProgress(
    val stage: String,
    val message: String
)

class TailscaleInstaller(private val context: Context) {
    companion object {
        const val PACKAGE = "com.tailscale.ipn"
        private const val STABLE = "https://pkgs.tailscale.com/stable/"
    }

    fun isInstalled(): Boolean = runCatching {
        context.packageManager.getPackageInfo(PACKAGE, 0)
        true
    }.getOrDefault(false)

    fun installLatest(onProgress: (InstallProgress) -> Unit) {
        val main = Handler(Looper.getMainLooper())
        fun emit(stage: String, message: String) {
            main.post { onProgress(InstallProgress(stage, message)) }
        }

        thread(name = "PhoneHubTailscaleInstall") {
            try {
                emit("download", "Finding latest official Tailscale package…")
                val page = httpText(STABLE)
                val match = Regex("""href=["']([^"']*tailscale-android-universal-([0-9.]+)\.apk)["']""")
                    .find(page) ?: error("Official Tailscale Android package was not found.")

                val relative = match.groupValues[1]
                val version = match.groupValues[2]
                val apkUrl = URL(URL(STABLE), relative).toString()
                val expected = httpText(apkUrl + ".sha256").trim().split(Regex("\\s+")).first().lowercase()

                emit("download", "Downloading Tailscale " + version + "…")
                val bytes = httpBytes(apkUrl)

                emit("verify", "Verifying SHA-256…")
                val actual = MessageDigest.getInstance("SHA-256")
                    .digest(bytes)
                    .joinToString("") { "%02x".format(it) }

                check(actual == expected) { "Tailscale package verification failed." }

                emit("install", "Installing verified Tailscale " + version + "…")
                installPackage(bytes)

                emit("install", "Install submitted to Android package manager.")
            } catch (t: Throwable) {
                emit("error", t.message ?: "Tailscale installation failed.")
            }
        }
    }

    private fun installPackage(bytes: ByteArray) {
        check(DevicePolicyController(context).isDeviceOwner()) {
            "PhoneHub must be Device Owner for managed installation."
        }

        val installer = context.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL).apply {
            setAppPackageName(PACKAGE)
            if (Build.VERSION.SDK_INT >= 31) {
                setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED)
            }
        }

        val sessionId = installer.createSession(params)
        val session = installer.openSession(sessionId)

        session.openWrite("tailscale.apk", 0, bytes.size.toLong()).use { out ->
            out.write(bytes)
            session.fsync(out)
        }

        val intent = Intent(context, PackageInstallReceiver::class.java)
            .setAction(PackageInstallReceiver.ACTION_INSTALL_RESULT)

        val flags = PendingIntent.FLAG_UPDATE_CURRENT or
            if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0

        val pending = PendingIntent.getBroadcast(
            context,
            sessionId,
            intent,
            flags
        )

        session.commit(pending.intentSender)
        session.close()
    }

    private fun httpText(url: String): String =
        String(httpBytes(url), Charsets.UTF_8)

    private fun httpBytes(url: String): ByteArray {
        val c = URL(url).openConnection() as HttpURLConnection
        c.connectTimeout = 15000
        c.readTimeout = 30000
        c.instanceFollowRedirects = true
        c.setRequestProperty("User-Agent", "PhoneHub/6.1")
        return try {
            check(c.responseCode in 200..299) { "HTTP " + c.responseCode }
            BufferedInputStream(c.inputStream).use { it.readBytes() }
        } finally {
            c.disconnect()
        }
    }
}
