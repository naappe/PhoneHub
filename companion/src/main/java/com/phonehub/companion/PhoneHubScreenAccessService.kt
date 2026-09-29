package com.phonehub.companion

import android.accessibilityservice.AccessibilityService
import android.graphics.Bitmap
import android.os.Build
import android.view.Display
import android.view.accessibility.AccessibilityEvent
import android.util.Base64
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

class PhoneHubScreenAccessService : AccessibilityService() {
    companion object {
        @Volatile private var instance: PhoneHubScreenAccessService? = null

        fun isReady(): Boolean = instance != null

        fun captureFrame(): JSONObject {
            val service = instance
                ?: return JSONObject().put("type","screen_error").put("message","Screen access is not enabled on the phone.")
            return service.capture()
        }
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
    }

    override fun onDestroy() {
        if (instance === this) instance = null
        super.onDestroy()
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}
    override fun onInterrupt() {}

    private fun capture(): JSONObject {
        if (Build.VERSION.SDK_INT < 30) {
            return JSONObject().put("type","screen_error").put("message","Remote screen requires Android 11 or newer.")
        }

        val latch = CountDownLatch(1)
        val result = AtomicReference<JSONObject>()
        takeScreenshot(Display.DEFAULT_DISPLAY, mainExecutor, object : TakeScreenshotCallback {
            override fun onSuccess(screenshot: ScreenshotResult) {
                try {
                    val hardware = screenshot.hardwareBuffer
                    val wrapped = Bitmap.wrapHardwareBuffer(hardware, screenshot.colorSpace)
                        ?: throw IllegalStateException("Android screenshot buffer unavailable")
                    val software = wrapped.copy(Bitmap.Config.ARGB_8888, false)
                    hardware.close()

                    val maxWidth = 720
                    val scale = if (software.width > maxWidth) maxWidth.toFloat() / software.width else 1f
                    val width = (software.width * scale).toInt().coerceAtLeast(1)
                    val height = (software.height * scale).toInt().coerceAtLeast(1)
                    val frame = if (width != software.width) Bitmap.createScaledBitmap(software, width, height, true) else software
                    val out = ByteArrayOutputStream()
                    frame.compress(Bitmap.CompressFormat.JPEG, 58, out)
                    val encoded = Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
                    result.set(JSONObject()
                        .put("type","screen_frame")
                        .put("encoding","jpeg-base64")
                        .put("width",width)
                        .put("height",height)
                        .put("data",encoded))
                    if (frame !== software) frame.recycle()
                    software.recycle()
                } catch (e: Exception) {
                    result.set(JSONObject().put("type","screen_error").put("message",e.message ?: e.javaClass.simpleName))
                } finally {
                    latch.countDown()
                }
            }

            override fun onFailure(errorCode: Int) {
                result.set(JSONObject().put("type","screen_error").put("message","Android screenshot failed ($errorCode)"))
                latch.countDown()
            }
        })

        if (!latch.await(5, TimeUnit.SECONDS)) {
            return JSONObject().put("type","screen_error").put("message","Timed out capturing Android screen.")
        }
        return result.get() ?: JSONObject().put("type","screen_error").put("message","No Android screen frame returned.")
    }
}
