package mv.phonehub.link

import kotlinx.serialization.Serializable

@Serializable
data class SignalMessage(
    val type: String,
    val sdp: String? = null,
    val candidate: String? = null,
    val sdpMid: String? = null,
    val sdpMLineIndex: Int? = null
)
