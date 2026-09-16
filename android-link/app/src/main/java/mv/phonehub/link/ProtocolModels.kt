package mv.phonehub.link

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put


data class CommandResult(
    val ok: Boolean,
    val type: String,
    val data: JsonObject = buildJsonObject {},
    val error: String? = null
)

object ProtocolModels {
    const val VERSION = 1

    fun canonicalUnsignedRequest(
        version: Int,
        pcId: String,
        nonce: String,
        timestamp: Long,
        type: String,
        payload: JsonObject
    ): String = canonicalJson(
        buildJsonObject {
            put("nonce", nonce)
            put("payload", payload)
            put("pcId", pcId)
            put("timestamp", timestamp)
            put("type", type)
            put("version", version)
        }
    )

    fun canonicalUnsignedResponse(
        ok: Boolean,
        type: String,
        data: JsonObject,
        error: String?,
        timestamp: Long
    ): String = canonicalJson(
        buildJsonObject {
            put("data", data)
            if (error == null) put("error", JsonPrimitive(null as String?)) else put("error", error)
            put("ok", ok)
            put("timestamp", timestamp)
            put("type", type)
        }
    )

    fun canonicalJson(element: JsonElement): String = when (element) {
        is JsonObject -> element.entries
            .sortedBy { it.key }
            .joinToString(prefix = "{", postfix = "}") { (key, value) ->
                "${JsonPrimitive(key)}:${canonicalJson(value)}"
            }
        is kotlinx.serialization.json.JsonArray -> element.joinToString(prefix = "[", postfix = "]") { canonicalJson(it) }
        else -> element.toString()
    }
}
