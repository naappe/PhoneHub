package mv.phonehub.link

import org.junit.Assert.*
import org.junit.Test

class AuthProtocolTest {
    @Test
    fun validSignaturePassesAndTamperingFails() {
        val secret = "01234567890123456789012345678901".toByteArray()
        val nonce = "n-123"
        val body = "{\"type\":\"device_status\"}"
        val signature = AuthProtocol.sign(secret, nonce, body)

        assertTrue(AuthProtocol.verify(secret, nonce, body, signature))
        assertFalse(AuthProtocol.verify(secret, nonce, body + "x", signature))
    }

    @Test
    fun pairingCodeIsSixDigits() {
        val code = PairingStore.generateHumanCode()
        assertTrue(code.matches(Regex("\\d{6}")))
    }
}
