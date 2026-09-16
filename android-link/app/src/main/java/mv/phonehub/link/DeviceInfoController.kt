package mv.phonehub.link

import android.content.Context
import android.os.BatteryManager
import android.os.Build


data class DeviceInfoSnapshot(
    val batteryPercent: Int,
    val manufacturer: String,
    val model: String,
    val androidVersion: String,
    val serviceState: String,
    val screenSharingActive: Boolean
)

interface DeviceInfoProvider {
    fun snapshot(): DeviceInfoSnapshot
}

class DeviceInfoController(private val context: Context) : DeviceInfoProvider {
    override fun snapshot(): DeviceInfoSnapshot {
        val batteryManager = context.getSystemService(BatteryManager::class.java)
        val battery = batteryManager?.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY) ?: -1
        return DeviceInfoSnapshot(
            batteryPercent = battery,
            manufacturer = Build.MANUFACTURER.orEmpty(),
            model = Build.MODEL.orEmpty(),
            androidVersion = Build.VERSION.RELEASE.orEmpty(),
            serviceState = PhoneHubService.currentState.name.lowercase(),
            screenSharingActive = ScreenShareService.isSharing
        )
    }
}
