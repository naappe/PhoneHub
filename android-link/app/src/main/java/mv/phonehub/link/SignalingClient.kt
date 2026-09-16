package mv.phonehub.link

import io.github.jan.supabase.createSupabaseClient
import io.github.jan.supabase.realtime.Realtime
import io.github.jan.supabase.realtime.broadcast
import io.github.jan.supabase.realtime.broadcastFlow
import io.github.jan.supabase.realtime.channel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch

class SignalingClient(
    private val scope: CoroutineScope,
    private val roomCode: String,
    private val onSignal: suspend (SignalMessage) -> Unit,
    private val onStatus: (String) -> Unit
) {
    private val supabase = createSupabaseClient(
        supabaseUrl = SUPABASE_URL,
        supabaseKey = SUPABASE_KEY
    ) {
        install(Realtime)
    }

    private val channel = supabase.channel("phonehub-link:$roomCode")
    private var collectorJob: Job? = null

    suspend fun connect() {
        collectorJob = scope.launch {
            channel.broadcastFlow<SignalMessage>(event = "signal").collect { message ->
                onSignal(message)
            }
        }
        channel.subscribe(blockUntilSubscribed = true)
        onStatus("Signaling connected")
    }

    suspend fun send(message: SignalMessage) {
        channel.broadcast(event = "signal", message = message)
    }

    suspend fun close() {
        collectorJob?.cancel()
        channel.unsubscribe()
        onStatus("Signaling closed")
    }

    companion object {
        const val SUPABASE_URL = "https://tmupbruwmwlrmewhoodn.supabase.co"
        const val SUPABASE_KEY = "sb_publishable_LAn1liS2zqMqlB33IQJxIw_NbgWKix1"
    }
}
