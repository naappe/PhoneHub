package com.phonehub.companion

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.graphics.ImageFormat
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.media.ImageReader
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import java.util.concurrent.Semaphore
import java.util.concurrent.TimeUnit

class CameraService : Service() {
    companion object {
        private const val CHANNEL = "phonehub_camera"
        private const val NOTIFICATION_ID = 7003
        const val ACTION_START = "com.phonehub.companion.START_CAMERA"
        const val ACTION_STOP = "com.phonehub.companion.STOP_CAMERA"
        const val EXTRA_LENS = "lens"

        @Volatile var active = false
        @Volatile var lens = "back"
        @Volatile var lastFrame: ByteArray? = null
        @Volatile var lastFrameAt = 0L

        fun start(context: Context, requestedLens: String) {
            val i = Intent(context, CameraService::class.java)
                .setAction(ACTION_START)
                .putExtra(EXTRA_LENS, requestedLens)
            ContextCompat.startForegroundService(context, i)
        }

        fun stop(context: Context) {
            context.startService(Intent(context, CameraService::class.java).setAction(ACTION_STOP))
        }
    }

    private var camera: CameraDevice? = null
    private var session: CameraCaptureSession? = null
    private var reader: ImageReader? = null
    private var thread: HandlerThread? = null
    private var handler: Handler? = null
    private val openClose = Semaphore(1)

    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "Samsung Secure camera", NotificationManager.IMPORTANCE_LOW))
        val n = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setContentTitle("Samsung Secure Camera")
            .setContentText("Camera service")
            .setOngoing(true)
            .setSilent(true)
            .build()
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTIFICATION_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA)
        } else {
            startForeground(NOTIFICATION_ID, n)
        }
        thread = HandlerThread("PhoneHubCamera").also { it.start() }
        handler = Handler(thread!!.looper)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            closeCamera()
            stopSelf()
            return START_NOT_STICKY
        }
        if (intent?.action == ACTION_START) {
            lens = if (intent.getStringExtra(EXTRA_LENS) == "front") "front" else "back"
            openCamera()
        }
        return START_NOT_STICKY
    }

    private fun openCamera() {
        if (ContextCompat.checkSelfPermission(this, android.Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            stopSelf()
            return
        }
        closeCamera()
        val manager = getSystemService(CameraManager::class.java)
        val wanted = if (lens == "front") CameraCharacteristics.LENS_FACING_FRONT else CameraCharacteristics.LENS_FACING_BACK
        val id = manager.cameraIdList.firstOrNull {
            manager.getCameraCharacteristics(it).get(CameraCharacteristics.LENS_FACING) == wanted
        } ?: return

        reader = ImageReader.newInstance(640, 480, ImageFormat.JPEG, 2)
        reader!!.setOnImageAvailableListener({ r ->
            val image = r.acquireLatestImage() ?: return@setOnImageAvailableListener
            image.use {
                val buffer = it.planes[0].buffer
                val bytes = ByteArray(buffer.remaining())
                buffer.get(bytes)
                lastFrame = bytes
                lastFrameAt = System.currentTimeMillis()
            }
        }, handler)

        if (!openClose.tryAcquire(2500, TimeUnit.MILLISECONDS)) return
        try {
            manager.openCamera(id, object : CameraDevice.StateCallback() {
                override fun onOpened(device: CameraDevice) {
                    openClose.release()
                    camera = device
                    createSession(device)
                }
                override fun onDisconnected(device: CameraDevice) {
                    openClose.release()
                    device.close()
                    active = false
                }
                override fun onError(device: CameraDevice, error: Int) {
                    openClose.release()
                    device.close()
                    active = false
                }
            }, handler)
        } catch (e: Exception) {
            openClose.release()
            active = false
            throw e
        }
    }

    private fun createSession(device: CameraDevice) {
        val surface = reader?.surface ?: return
        device.createCaptureSession(listOf(surface), object : CameraCaptureSession.StateCallback() {
            override fun onConfigured(s: CameraCaptureSession) {
                session = s
                val request = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
                    addTarget(surface)
                }.build()
                s.setRepeatingRequest(request, null, handler)
                active = true
            }
            override fun onConfigureFailed(s: CameraCaptureSession) {
                active = false
            }
        }, handler)
    }

    @Synchronized
    private fun closeCamera() {
        active = false
        try { session?.close() } catch (_: Exception) {}
        try { camera?.close() } catch (_: Exception) {}
        try { reader?.close() } catch (_: Exception) {}
        session = null
        camera = null
        reader = null
        lastFrame = null
    }

    override fun onDestroy() {
        closeCamera()
        try { thread?.quitSafely() } catch (_: Exception) {}
        thread = null
        handler = null
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
