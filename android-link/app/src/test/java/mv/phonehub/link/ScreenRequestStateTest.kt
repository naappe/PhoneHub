package mv.phonehub.link

import org.junit.Assert.assertEquals
import org.junit.Test

class ScreenRequestStateTest {
    @Test
    fun inactiveProjectionRequiresPermission() {
        assertEquals("permission_required", ScreenRequestState(isSharing = false).resultCode)
    }

    @Test
    fun activeProjectionReportsAlreadySharing() {
        assertEquals("already_sharing", ScreenRequestState(isSharing = true).resultCode)
    }
}
