package com.phonehub.companion

import android.app.*
import android.content.*
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.*
import androidx.core.app.NotificationCompat
import java.io.ByteArrayOutputStream

class ScreenCaptureService : Service() {
    companion object {
        private const val CHANNEL = "phonehub_screen"
        private const val NOTIFICATION_ID = 7002
        private const val EXTRA_CODE = "projection_code"
        private const val EXTRA_DATA = "projection_data"
        @Volatile var active = false
        @Volatile var latestJpeg: ByteArray? = null
        @Volatile var frameWidth = 0
        @Volatile var frameHeight = 0
        @Volatile var lastFrameAt = 0L

        fun start(context: Context, resultCode: Int, data: Intent) {
            val i = Intent(context, ScreenCaptureService::class.java)
                .putExtra(EXTRA_CODE, resultCode)
                .putExtra(EXTRA_DATA, data)
            context.startForegroundService(i)
        }
        fun stop(context: Context) {
            context.stopService(Intent(context, ScreenCaptureService::class.java))
        }
    }

    private var projection: MediaProjection? = null
    private var display: VirtualDisplay? = null
    private var reader: ImageReader? = null
    private var worker: HandlerThread? = null

    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "PhoneHub screen sharing", NotificationManager.IMPORTANCE_LOW))
        val n = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_view)
            .setContentTitle("PhoneHub Screen")
            .setContentText("Screen sharing is active")
            .setOngoing(true)
            .setSilent(true)
            .build()
        if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIFICATION_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        else startForeground(NOTIFICATION_ID, n)
    }

    @Suppress("DEPRECATION")
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (active) return START_NOT_STICKY
        val code = intent?.getIntExtra(EXTRA_CODE, Activity.RESULT_CANCELED) ?: Activity.RESULT_CANCELED
        val data = intent?.getParcelableExtra<Intent>(EXTRA_DATA)
        if (code != Activity.RESULT_OK || data == null) { stopSelf(); return START_NOT_STICKY }

        val metrics = resources.displayMetrics
        val sourceW = metrics.widthPixels
        val sourceH = metrics.heightPixels
        val maxW = 720
        val scale = if (sourceW > maxW) maxW.toFloat() / sourceW else 1f
        val w = (sourceW * scale).toInt().coerceAtLeast(1)
        val h = (sourceH * scale).toInt().coerceAtLeast(1)
        frameWidth = w; frameHeight = h

        worker = HandlerThread("phonehub-screen-capture").also { it.start() }
        val handler = Handler(worker!!.looper)
        val manager = getSystemService(MediaProjectionManager::class.java)
        projection = manager.getMediaProjection(code, data)
        projection?.registerCallback(object : MediaProjection.Callback() {
            override fun onStop() { stopSelf() }
        }, handler)

        reader = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 2)
        reader?.setOnImageAvailableListener({ r ->
            val image = r.acquireLatestImage() ?: return@setOnImageAvailableListener
            try {
                val plane = image.planes[0]
                val pixelStride = plane.pixelStride
                val rowStride = plane.rowStride
                val paddedWidth = rowStride / pixelStride
                val padded = Bitmap.createBitmap(paddedWidth, h, Bitmap.Config.ARGB_8888)
                padded.copyPixelsFromBuffer(plane.buffer)
                val cropped = if (paddedWidth == w) padded else Bitmap.createBitmap(padded, 0, 0, w, h)
                val out = ByteArrayOutputStream()
                cropped.compress(Bitmap.CompressFormat.JPEG, 55, out)
                latestJpeg = out.toByteArray()
                lastFrameAt = System.currentTimeMillis()
                if (cropped !== padded) cropped.recycle()
                padded.recycle()
            } catch (_: Exception) {
            } finally {
                image.close()
            }
        }, handler)

        display = projection?.createVirtualDisplay(
            "PhoneHubScreen", w, h, metrics.densityDpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            reader?.surface, null, handler
        )
        active = display != null
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        active = false
        latestJpeg = null
        lastFrameAt = 0L
        try { display?.release() } catch (_: Exception) {}
        try { reader?.close() } catch (_: Exception) {}
        try { projection?.stop() } catch (_: Exception) {}
        worker?.quitSafely()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
