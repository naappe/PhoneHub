package mv.phonehub.link

import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SessionTest {
    @Test
    fun roomCodeIsSixDigits() {
        val code = createRoomCode()
        assertTrue(code.matches(Regex("\\d{6}")))
    }

    @Test
    fun roomCodesChange() {
        val first = createRoomCode()
        var second = createRoomCode()
        repeat(10) {
            if (second != first) return@repeat
            second = createRoomCode()
        }
        assertNotEquals(first, second)
    }
}
