package mv.phonehub.link

import java.util.Base64
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PairingRequestProcessorTest {
    private val now = 1_800_000_000_000L
    private val secret = "01234567890123456789012345678901".toByteArray()

    @Test
    fun activePairingCodeCanEstablishFirstClient() {
        val processor = PhoneHubRequestProcessor(
            pairedClientProvider = { null },
            router = CommandRouter(FakePairingDeviceInfo()),
            nowMillis = { now },
            pairingHandler = { pcId, code ->
                if (pcId == "pc-new" && code == "123456") {
                    PairedClient(pcId = pcId, secret = secret, pairedAtMillis = now)
                } else null
            }
        )

        val response = processor.process(pairingRequest("123456"))
            .let { Json.parseToJsonElement(it).jsonObject }

        assertTrue(response["ok"]!!.jsonPrimitive.content.toBoolean())
        assertEquals("pair", response["type"]!!.jsonPrimitive.content)
        assertEquals(
            Base64.getEncoder().encodeToString(secret),
            response["data"]!!.jsonObject["secret"]!!.jsonPrimitive.content
        )
        assertTrue(response["signature"]!!.jsonPrimitive.content.isNotBlank())
    }

    @Test
    fun wrongPairingCodeIsRejectedWithoutSecret() {
        val processor = PhoneHubRequestProcessor(
            pairedClientProvider = { null },
            router = CommandRouter(FakePairingDeviceInfo()),
            nowMillis = { now },
            pairingHandler = { _, _ -> null }
        )

        val response = processor.process(pairingRequest("000000"))
            .let { Json.parseToJsonElement(it).jsonObject }

        assertFalse(response["ok"]!!.jsonPrimitive.content.toBoolean())
        assertEquals("pairing_failed", response["error"]!!.jsonPrimitive.content)
        assertTrue(response["data"]!!.jsonObject["secret"] == null)
    }

    private fun pairingRequest(code: String): String = buildJsonObject {
        put("version", ProtocolModels.VERSION)
        put("pcId", "pc-new")
        put("nonce", "pair-nonce-1")
        put("timestamp", now)
        put("type", "pair")
        put("payload", buildJsonObject { put("code", code) })
        put("signature", "")
    }.toString()
}

private class FakePairingDeviceInfo : DeviceInfoProvider {
    override fun snapshot(): DeviceInfoSnapshot = DeviceInfoSnapshot(
        batteryPercent = 80,
        manufacturer = "Test",
        model = "Phone",
        androidVersion = "14",
        serviceState = "active",
        screenSharingActive = false
    )
}
