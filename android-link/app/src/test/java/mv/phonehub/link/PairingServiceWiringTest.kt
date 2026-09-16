package mv.phonehub.link

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PairingServiceWiringTest {
    private val secret = "01234567890123456789012345678901".toByteArray()

    @Test
    fun successfulPairingReturnsClientAndNotifiesService() {
        var notified = false
        val handler = safePairingHandler(
            completePairing = { pcId, code ->
                require(code == "123456")
                PairedClient(pcId = pcId, secret = secret, pairedAtMillis = 123L)
            },
            onPaired = { notified = true }
        )

        val paired = handler("pc-new", "123456")

        assertEquals("pc-new", paired?.pcId)
        assertTrue(notified)
    }

    @Test
    fun invalidPairingReturnsNullAndDoesNotNotifyService() {
        var notified = false
        val handler = safePairingHandler(
            completePairing = { _, _ -> error("invalid code") },
            onPaired = { notified = true }
        )

        val paired = handler("pc-new", "000000")

        assertNull(paired)
        assertFalse(notified)
    }
}
