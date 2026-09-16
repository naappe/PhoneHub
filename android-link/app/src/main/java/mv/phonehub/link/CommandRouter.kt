package mv.phonehub.link

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

class CommandRouter(
    private val deviceInfoProvider: DeviceInfoProvider,
    private val screenRequestHandler: (() -> Unit)? = null
) {
    fun handle(type: String, payload: JsonObject): CommandResult = when (type) {
        "ping" -> CommandResult(
            ok = true,
            type = type,
            data = buildJsonObject { put("reply", "pong") }
        )

        "device_status" -> {
            val snapshot = deviceInfoProvider.snapshot()
            CommandResult(
                ok = true,
                type = type,
                data = buildJsonObject {
                    put("batteryPercent", snapshot.batteryPercent)
                    put("manufacturer", snapshot.manufacturer)
                    put("model", snapshot.model)
                    put("androidVersion", snapshot.androidVersion)
                    put("serviceState", snapshot.serviceState)
                    put("screenSharingActive", snapshot.screenSharingActive)
                }
            )
        }

        "screen_request" -> {
            screenRequestHandler?.invoke()
            CommandResult(
                ok = true,
                type = type,
                data = buildJsonObject {
                    put("status", "consent_required")
                }
            )
        }

        else -> CommandResult(
            ok = false,
            type = type,
            error = "unsupported_command"
        )
    }
}
