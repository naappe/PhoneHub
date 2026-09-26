package com.phonehub.notifier

import android.app.*
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.IBinder
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.Executors

class PhoneHubRemoteService : Service() {
    companion object {
        const val PORT = 8765
        const val ACTION_START_SERVER = "com.phonehub.notifier.START_REMOTE_SERVER"
        const val ACTION_START_CAPTURE = "com.phonehub.notifier.START_REMOTE_CAPTURE"
        const val ACTION_STOP_CAPTURE = "com.phonehub.notifier.STOP_REMOTE_CAPTURE"
        const val EXTRA_RESULT_CODE = "result_code"
        const val EXTRA_RESULT_DATA = "result_data"
        private const val CHANNEL_ID = "phonehub_remote"
        private const val NOTIFICATION_ID = 8765
        @Volatile var latestFrame: ByteArray? = null
    }

    private val pool = Executors.newCachedThreadPool()
    private var server: ServerSocket? = null
    private var mediaProjection: MediaProjection? = null
    private var imageReader: ImageReader? = null
    private var virtualDisplay: VirtualDisplay? = null

    override fun onCreate() {
        super.onCreate()
        createChannel()
        startRemoteForeground("PhoneHub remote service ready")
        startServer()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START_CAPTURE -> {
                val code = intent.getIntExtra(EXTRA_RESULT_CODE, Activity.RESULT_CANCELED)
                @Suppress("DEPRECATION")
                val data = if (Build.VERSION.SDK_INT >= 33) {
                    intent.getParcelableExtra(EXTRA_RESULT_DATA, Intent::class.java)
                } else {
                    intent.getParcelableExtra(EXTRA_RESULT_DATA)
                }
                if (code == Activity.RESULT_OK && data != null) startCapture(code, data)
            }
            ACTION_STOP_CAPTURE -> stopCapture()
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            val channel = NotificationChannel(CHANNEL_ID, "PhoneHub Remote", NotificationManager.IMPORTANCE_LOW)
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }

    private fun startRemoteForeground(text: String) {
        val openApp = PendingIntent.getActivity(this, 1, Intent(this, MainActivity::class.java), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notification = Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
            .setContentTitle("PhoneHub Agent")
            .setContentText(text)
            .setContentIntent(openApp)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        } else startForeground(NOTIFICATION_ID, notification)
    }

    private fun startServer() {
        if (server != null) return
        pool.execute {
            try {
                server = ServerSocket(PORT)
                while (!Thread.currentThread().isInterrupted) {
                    val socket = server?.accept() ?: break
                    pool.execute { handle(socket) }
                }
            } catch (_: Throwable) {}
        }
    }

    private fun handle(socket: Socket) {
        socket.use { s ->
            try {
                s.soTimeout = 5000
                val input = BufferedInputStream(s.getInputStream())
                val output = BufferedOutputStream(s.getOutputStream())
                val requestLine = readLine(input) ?: return
                val parts = requestLine.split(" ")
                val method = parts.getOrNull(0) ?: "GET"
                val path = parts.getOrNull(1) ?: "/"
                while (true) {
                    val line = readLine(input) ?: break
                    if (line.isEmpty()) break
                }
                when {
                    method == "GET" && path == "/health" -> {
                        val state = if (latestFrame != null) "active" else "idle"
                        writeResponse(output, 200, "application/json", ("{\"service\":\"phonehub-agent\",\"screen\":\"" + state + "\",\"port\":" + PORT + "}").toByteArray())
                    }
                    method == "POST" && path == "/screen/request" -> {
                        showCaptureRequestNotification()
                        writeResponse(output, 202, "application/json", "{\"status\":\"approval_required\"}".toByteArray())
                    }
                    method == "POST" && path == "/screen/stop" -> {
                        stopCapture()
                        writeResponse(output, 200, "application/json", "{\"status\":\"stopped\"}".toByteArray())
                    }
                    method == "GET" && path == "/screen/frame" -> {
                        val frame = latestFrame
                        if (frame == null) writeResponse(output, 409, "application/json", "{\"status\":\"screen_not_active\"}".toByteArray())
                        else writeResponse(output, 200, "image/jpeg", frame)
                    }
                    else -> writeResponse(output, 404, "text/plain", "Not found".toByteArray())
                }
            } catch (_: Throwable) {}
        }
    }

    private fun showCaptureRequestNotification() {
        val intent = Intent(this, ScreenCaptureActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        val pending = PendingIntent.getActivity(this, 2, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val n = Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_menu_view)
            .setContentTitle("PhoneHub screen request")
            .setContentText("Tap to approve screen sharing with your PC")
            .setContentIntent(pending)
            .setAutoCancel(true)
            .build()
        getSystemService(NotificationManager::class.java).notify(8766, n)
    }

    private fun startCapture(resultCode: Int, data: Intent) {
        stopCapture()
        val mgr = getSystemService(MediaProjectionManager::class.java)
        val projection = mgr.getMediaProjection(resultCode, data) ?: return
        mediaProjection = projection
        projection.registerCallback(object : MediaProjection.Callback() {
            override fun onStop() { stopCapture() }
        }, null)
        val metrics = resources.displayMetrics
        val width = metrics.widthPixels.coerceAtMost(1080)
        val height = (metrics.heightPixels * (width.toFloat() / metrics.widthPixels)).toInt()
        val density = metrics.densityDpi
        val reader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)
        imageReader = reader
        reader.setOnImageAvailableListener({ r ->
            val image = r.acquireLatestImage() ?: return@setOnImageAvailableListener
            try {
                val plane = image.planes[0]
                val buffer = plane.buffer
                val pixelStride = plane.pixelStride
                val rowStride = plane.rowStride
                val rowPadding = rowStride - pixelStride * width
                val padded = width + rowPadding / pixelStride
                val bitmap = Bitmap.createBitmap(padded, height, Bitmap.Config.ARGB_8888)
                bitmap.copyPixelsFromBuffer(buffer)
                val cropped = Bitmap.createBitmap(bitmap, 0, 0, width, height)
                val out = java.io.ByteArrayOutputStream()
                cropped.compress(Bitmap.CompressFormat.JPEG, 60, out)
                latestFrame = out.toByteArray()
                cropped.recycle()
                bitmap.recycle()
            } finally { image.close() }
        }, null)
        virtualDisplay = projection.createVirtualDisplay("PhoneHubRemoteScreen", width, height, density, DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, reader.surface, null, null)
        startRemoteForeground("Remote screen active")
    }

    private fun stopCapture() {
        latestFrame = null
        virtualDisplay?.release(); virtualDisplay = null
        imageReader?.close(); imageReader = null
        val p = mediaProjection; mediaProjection = null
        if (p != null) try { p.stop() } catch (_: Throwable) {}
        startRemoteForeground("PhoneHub remote service ready")
    }

    private fun readLine(input: BufferedInputStream): String? {
        val bytes = ArrayList<Byte>()
        while (true) {
            val b = input.read()
            if (b == -1) return if (bytes.isEmpty()) null else bytes.toByteArray().toString(Charsets.UTF_8)
            if (b == 10) break
            if (b != 13) bytes.add(b.toByte())
        }
        return bytes.toByteArray().toString(Charsets.UTF_8)
    }

    private fun writeResponse(out: BufferedOutputStream, code: Int, type: String, body: ByteArray) {
        val reason = when (code) { 200 -> "OK"; 202 -> "Accepted"; 409 -> "Conflict"; else -> "Not Found" }
        val head = "HTTP/1.1 " + code + " " + reason + "\r\nContent-Type: " + type + "\r\nContent-Length: " + body.size + "\r\nConnection: close\r\n\r\n"
        out.write(head.toByteArray()); out.write(body); out.flush()
    }

    override fun onDestroy() {
        try { server?.close() } catch (_: Throwable) {}
        server = null
        stopCapture()
        pool.shutdownNow()
        super.onDestroy()
    }
}