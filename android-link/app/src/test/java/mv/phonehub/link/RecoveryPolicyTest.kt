package mv.phonehub.link

import org.junit.Assert.assertEquals
import org.junit.Test

class RecoveryPolicyTest {
    @Test
    fun backoffIsBounded() {
        assertEquals(15L, RecoveryPolicy.nextDelaySeconds(0))
        assertEquals(30L, RecoveryPolicy.nextDelaySeconds(1))
        assertEquals(60L, RecoveryPolicy.nextDelaySeconds(2))
        assertEquals(900L, RecoveryPolicy.nextDelaySeconds(20))
    }
}
