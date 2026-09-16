package mv.phonehub.link

import org.junit.Assert.assertEquals
import org.junit.Test

class PairingUiStateTest {
    @Test
    fun pairedActiveStateHasExpectedCopy() {
        val state = PairingUiState(serviceEnabled = true, paired = true)
        assertEquals("Active - Paired", state.title)
    }

    @Test
    fun disabledStateHasExpectedCopy() {
        val state = PairingUiState(serviceEnabled = false, paired = false)
        assertEquals("Service Off", state.title)
    }
}
