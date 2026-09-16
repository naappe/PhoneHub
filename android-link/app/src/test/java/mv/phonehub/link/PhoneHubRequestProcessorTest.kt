package mv.phonehub.link

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PhoneHubRequestProcessorTest {
    private val secret = "01234567890123456789012345678901".toByteArray()
    private val now = 1_800_000_000_000L

    @Test
    fun validSignedPingIsAccepted() {
        val processor = processor()
        val response = Json.parseToJsonElement(signedRequest("ping")).jsonObject
            .let { request -> processor.process(Json.encodeToString(JsonObject.serializer(), request)) }
            .let { Json.parseToJsonElement(it).jsonObject }

        assertTrue(response["ok"]!!.jsonPrimitive.content.toBoolean())
        assertEquals("ping", response["type"]!!.jsonPrimitive.content)
        assertEquals("pong", response["data"]!!.jsonObject["reply"]!!.jsonPrimitive.content)
    }

    @Test
    fun invalidSignatureIsRejected() {
        val processor = processor()
        val bad = Json.parseToJsonElement(signedRequest("ping")).jsonObject.toMutableMap().apply {
            this["signature"] = kotlinx.serialization.json.JsonPrimitive("00")
        }
        val response = processor.process(Json.encodeToString(JsonObject.serializer(), JsonObject(bad)))
            .let { Json.parseToJsonElement(it).jsonObject }

        assertFalse(response["ok"]!!.jsonPrimitive.content.toBoolean())
        assertEquals("authentication_failed", response["error"]!!.jsonPrimitive.content)
    }

    private fun processor(): PhoneHubRequestProcessor = PhoneHubRequestProcessor(
        pairedClientProvider = {
            PairedClient(pcId = "pc-test", secret = secret, pairedAtMillis = now - 1000)
        },
        router = CommandRouter(FakeProcessorDeviceInfo()),
        nowMillis = { now }
    )

    private fun signedRequest(type: String): String {
        val payload = buildJsonObject { }
        val nonce = "nonce-123"
        val unsigned = ProtocolModels.canonicalUnsignedRequest(
            version = ProtocolModels.VERSION,
            pcId = "pc-test",
            nonce = nonce,
            timestamp = now,
            type = type,
            payload = payload
        )
        val signature = AuthProtocol.sign(secret, nonce, unsigned)
        return buildJsonObject {
            put("version", ProtocolModels.VERSION)
            put("pcId", "pc-test")
            put("nonce", nonce)
            put("timestamp", now)
            put("type", type)
            put("payload", payload)
            put("signature", signature)
        }.toString()
    }
}

private class FakeProcessorDeviceInfo : DeviceInfoProvider {
    override fun snapshot(): DeviceInfoSnapshot = DeviceInfoSnapshot(
        batteryPercent = 80,
        manufacturer = "Test",
        model = "Phone",
        androidVersion = "14",
        serviceState = "active",
        screenSharingActive = false
    )
}
