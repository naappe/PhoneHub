package mv.phonehub.link

import android.content.Context

/**
 * Stores only the fact that an authenticated paired PC requested screen access.
 * It never stores or fabricates MediaProjection permission. The user must still
 * approve Android's system capture dialog from MainActivity.
 */
object ScreenRequestStore {
    private const val PREFS_NAME = "phonehub_screen_requests"
    private const val KEY_PENDING_AT = "pending_at"
    private const val MAX_AGE_MILLIS = 5 * 60 * 1000L

    fun markPending(context: Context, nowMillis: Long = System.currentTimeMillis()) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putLong(KEY_PENDING_AT, nowMillis)
            .apply()
    }

    fun isPending(context: Context, nowMillis: Long = System.currentTimeMillis()): Boolean {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val pendingAt = prefs.getLong(KEY_PENDING_AT, 0L)
        if (pendingAt <= 0L) return false
        val valid = nowMillis >= pendingAt && nowMillis - pendingAt <= MAX_AGE_MILLIS
        if (!valid) prefs.edit().remove(KEY_PENDING_AT).apply()
        return valid
    }

    fun clear(context: Context) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .remove(KEY_PENDING_AT)
            .apply()
    }
}
