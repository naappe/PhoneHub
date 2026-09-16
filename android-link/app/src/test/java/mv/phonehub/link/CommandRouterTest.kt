package mv.phonehub.link

import kotlinx.serialization.json.buildJsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CommandRouterTest {
    @Test
    fun unknownCommandIsRejected() {
        val router = CommandRouter(FakeDeviceInfoController())
        val result = router.handle("does_not_exist", buildJsonObject {})

        assertFalse(result.ok)
        assertEquals("unsupported_command", result.error)
    }

    @Test
    fun pingReturnsPong() {
        val router = CommandRouter(FakeDeviceInfoController())
        val result = router.handle("ping", buildJsonObject {})

        assertTrue(result.ok)
        assertEquals("pong", result.data["reply"]?.toString()?.trim('"'))
    }
}

private class FakeDeviceInfoController : DeviceInfoProvider {
    override fun snapshot(): DeviceInfoSnapshot = DeviceInfoSnapshot(
        batteryPercent = 80,
        manufacturer = "Test",
        model = "Phone",
        androidVersion = "14",
        serviceState = "ACTIVE",
        screenSharingActive = false
    )
}
