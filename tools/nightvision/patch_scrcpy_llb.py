from pathlib import Path

path = Path("scrcpy/server/src/main/java/com/genymobile/scrcpy/video/CameraCapture.java")
text = path.read_text(encoding="utf-8")

replacements = [
    (
        "import android.hardware.camera2.CameraManager;\nimport android.hardware.camera2.CaptureFailure;\nimport android.hardware.camera2.CaptureRequest;",
        "import android.hardware.camera2.CameraManager;\nimport android.hardware.camera2.CameraMetadata;\nimport android.hardware.camera2.CaptureFailure;\nimport android.hardware.camera2.CaptureRequest;\nimport android.hardware.camera2.CaptureResult;\nimport android.hardware.camera2.TotalCaptureResult;"
    ),
    (
        "import android.media.MediaCodec;\nimport android.os.Handler;",
        "import android.media.MediaCodec;\nimport android.os.Build;\nimport android.os.Handler;"
    ),
    (
        "    private Range<Float> zoomRange;\n",
        "    private Range<Float> zoomRange;\n    private Integer lastLowLightBoostState;\n"
    ),
    (
        """                CameraManager cameraManager = ServiceManager.getCameraManager();
                try {
                    CameraCharacteristics characteristics = cameraManager.getCameraCharacteristics(cameraId);
                    zoomRange = characteristics.get(CameraCharacteristics.CONTROL_ZOOM_RATIO_RANGE);
                } catch (CameraAccessException e) {
                    Ln.w("Could not get camera characteristics");
                }

                try {
                    requestBuilder = cameraDevice.createCaptureRequest(CameraDevice.TEMPLATE_RECORD);
                    requestBuilder.addTarget(captureSurface);
""",
        """                CameraManager cameraManager = ServiceManager.getCameraManager();
                boolean lowLightBoostSupported = false;
                try {
                    CameraCharacteristics characteristics = cameraManager.getCameraCharacteristics(cameraId);
                    zoomRange = characteristics.get(CameraCharacteristics.CONTROL_ZOOM_RATIO_RANGE);

                    if (Build.VERSION.SDK_INT >= AndroidVersions.API_35_ANDROID_15) {
                        int[] aeModes = characteristics.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_MODES);
                        if (aeModes != null) {
                            for (int aeMode : aeModes) {
                                if (aeMode == CameraMetadata.CONTROL_AE_MODE_ON_LOW_LIGHT_BOOST_BRIGHTNESS_PRIORITY) {
                                    lowLightBoostSupported = true;
                                    break;
                                }
                            }
                        }

                        Range<Float> luminanceRange =
                                characteristics.get(CameraCharacteristics.CONTROL_LOW_LIGHT_BOOST_INFO_LUMINANCE_RANGE);
                        Ln.i("AndroidBridge LLB support: " + lowLightBoostSupported
                                + ", luminance range: " + luminanceRange);
                    }
                } catch (CameraAccessException e) {
                    Ln.w("Could not get camera characteristics");
                }

                try {
                    requestBuilder = cameraDevice.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
                    requestBuilder.addTarget(captureSurface);

                    if (lowLightBoostSupported) {
                        requestBuilder.set(
                                CaptureRequest.CONTROL_AE_MODE,
                                CameraMetadata.CONTROL_AE_MODE_ON_LOW_LIGHT_BOOST_BRIGHTNESS_PRIORITY);
                        Ln.i("AndroidBridge LLB requested");
                    } else {
                        Ln.w("AndroidBridge LLB is not exposed by camera " + cameraId + "; using normal AE");
                    }
"""
    ),
    (
        """            @Override
            public void onCaptureFailed(CameraCaptureSession session, CaptureRequest request, CaptureFailure failure) {
                Ln.w("Camera capture failed: frame " + failure.getFrameNumber());
            }
""",
        """            @Override
            public void onCaptureFailed(CameraCaptureSession session, CaptureRequest request, CaptureFailure failure) {
                Ln.w("Camera capture failed: frame " + failure.getFrameNumber());
            }

            @Override
            public void onCaptureCompleted(CameraCaptureSession session, CaptureRequest request, TotalCaptureResult result) {
                if (Build.VERSION.SDK_INT >= AndroidVersions.API_35_ANDROID_15) {
                    Integer aeMode = result.get(CaptureResult.CONTROL_AE_MODE);
                    Integer state = result.get(CaptureResult.CONTROL_LOW_LIGHT_BOOST_STATE);
                    if (state != null && !state.equals(lastLowLightBoostState)) {
                        lastLowLightBoostState = state;
                        Ln.i("AndroidBridge LLB state: "
                                + (state == CameraMetadata.CONTROL_LOW_LIGHT_BOOST_STATE_ACTIVE ? "ACTIVE" : "INACTIVE")
                                + ", AE mode=" + aeMode);
                    }
                }
            }
"""
    ),
]

for old, new in replacements:
    if old not in text:
        raise SystemExit("Patch anchor not found:\n" + old[:240])
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
print("Patched scrcpy v4.1 CameraCapture.java for Android 15+ Low Light Boost AE.")
