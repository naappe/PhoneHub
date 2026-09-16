package mv.phonehub.link

import org.junit.Assert.assertEquals
import org.junit.Test

class PhoneHubServiceStateTest {
    @Test
    fun notificationCopyReflectsState() {
        assertEquals("Active - waiting for paired PC", ServiceState.WAITING_FOR_PAIRING.notificationText)
        assertEquals("Active - paired PC connected", ServiceState.CONNECTED.notificationText)
    }
}
