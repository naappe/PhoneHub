package mv.phonehub.link

object RecoveryPolicy {
    private const val INITIAL_DELAY_SECONDS = 15L
    private const val MAX_DELAY_SECONDS = 900L

    fun nextDelaySeconds(attempt: Int): Long {
        var delay = INITIAL_DELAY_SECONDS
        repeat(attempt.coerceAtLeast(0).coerceAtMost(30)) {
            delay = (delay * 2L).coerceAtMost(MAX_DELAY_SECONDS)
        }
        return delay
    }
}
