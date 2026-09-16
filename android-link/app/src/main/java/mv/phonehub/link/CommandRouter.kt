package mv.phonehub.link

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put


data class ScreenRequestState(val isSharing: Boolean) {
    val resultCode: String
        get() = if (isSharing) "already_sharing" else "permission_required"
}

class CommandRouter(
    private val deviceInfoProvider: DeviceInfoProvider,
    private val screenRequestHandler: (() -> Unit)? = null,
    private val screenSharingProvider: () -> Boolean = { false }
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
            val state = ScreenRequestState(screenSharingProvider())
            if (state.isSharing) {
                CommandResult(
                    ok = true,
                    type = type,
                    data = buildJsonObject {
                        put("status", state.resultCode)
                    }
                )
            } else {
                screenRequestHandler?.invoke()
                CommandResult(
                    ok = false,
                    type = type,
                    data = buildJsonObject {
                        put("status", state.resultCode)
                        put("permission", "media_projection")
                    },
                    error = "permission_required"
                )
            }
        }

        else -> CommandResult(
            ok = false,
            type = type,
            error = "unsupported_command"
        )
    }
}
