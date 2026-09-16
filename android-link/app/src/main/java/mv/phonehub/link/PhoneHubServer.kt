package mv.phonehub.link

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.content
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import kotlinx.serialization.json.put
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketException
import java.util.LinkedHashSet
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

class PhoneHubRequestProcessor(
    private val pairedClientProvider: () -> PairedClient?,
    private val router: CommandRouter,
    private val nowMillis: () -> Long = { System.currentTimeMillis() },
    private val onAuthenticatedRequest: (() -> Unit)? = null
) {
    private val usedNonces = LinkedHashSet<String>()

    fun process(rawRequest: String): String {
        val parsed = try {
            Json.parseToJsonElement(rawRequest).jsonObject
        } catch (_: Exception) {
            return unsignedError("error", "malformed_request")
        }

        val version = parsed["version"]?.jsonPrimitive?.intOrNullCompat()
            ?: return unsignedError("error", "malformed_request")
        val pcId = parsed["pcId"]?.jsonPrimitive?.contentOrNullCompat()
            ?: return unsignedError("error", "malformed_request")
        val nonce = parsed["nonce"]?.jsonPrimitive?.contentOrNullCompat()
            ?: return unsignedError("error", "malformed_request")
        val timestamp = parsed["timestamp"]?.jsonPrimitive?.longOrNullCompat()
            ?: return unsignedError("error", "malformed_request")
        val type = parsed["type"]?.jsonPrimitive?.contentOrNullCompat()
            ?: return unsignedError("error", "malformed_request")
        val payload = parsed["payload"] as? JsonObject
            ?: return unsignedError(type, "malformed_request")
        val signature = parsed["signature"]?.jsonPrimitive?.contentOrNullCompat()
            ?: return unsignedError(type, "malformed_request")

        val paired = pairedClientProvider()
            ?: return unsignedError(type, "not_paired")

        if (version != ProtocolModels.VERSION || pcId != paired.pcId) {
            return signedError(type, "authentication_failed", paired.secret, nonce)
        }

        val now = nowMillis()
        if (timestamp < now - MAX_CLOCK_SKEW_MILLIS || timestamp > now + MAX_CLOCK_SKEW_MILLIS) {
            return signedError(type, "stale_request", paired.secret, nonce)
        }

        val unsigned = ProtocolModels.canonicalUnsignedRequest(
            version = version,
            pcId = pcId,
            nonce = nonce,
            timestamp = timestamp,
            type = type,
            payload = payload
        )
        if (!AuthProtocol.verify(paired.secret, nonce, unsigned, signature)) {
            return signedError(type, "authentication_failed", paired.secret, nonce)
        }

        if (!rememberNonce(nonce)) {
            return signedError(type, "replayed_request", paired.secret, nonce)
        }

        onAuthenticatedRequest?.invoke()
        return signedResult(router.handle(type, payload), paired.secret, nonce)
    }

    private fun rememberNonce(nonce: String): Boolean = synchronized(usedNonces) {
        if (nonce in usedNonces) return@synchronized false
        usedNonces.add(nonce)
        while (usedNonces.size > MAX_NONCES) {
            val first = usedNonces.firstOrNull() ?: break
            usedNonces.remove(first)
        }
        true
    }

    private fun signedResult(result: CommandResult, secret: ByteArray, nonce: String): String {
        val timestamp = nowMillis()
        val canonical = ProtocolModels.canonicalUnsignedResponse(
            ok = result.ok,
            type = result.type,
            data = result.data,
            error = result.error,
            timestamp = timestamp
        )
        val signature = AuthProtocol.sign(secret, nonce, canonical)
        return buildResponse(result.ok, result.type, result.data, result.error, timestamp, signature)
    }

    private fun signedError(type: String, error: String, secret: ByteArray, nonce: String): String =
        signedResult(CommandResult(ok = false, type = type, error = error), secret, nonce)

    private fun unsignedError(type: String, error: String): String =
        buildResponse(
            ok = false,
            type = type,
            data = buildJsonObject {},
            error = error,
            timestamp = nowMillis(),
            signature = ""
        )

    private fun buildResponse(
        ok: Boolean,
        type: String,
        data: JsonObject,
        error: String?,
        timestamp: Long,
        signature: String
    ): String = buildJsonObject {
        put("ok", ok)
        put("type", type)
        put("data", data)
        if (error == null) put("error", JsonPrimitive(null as String?)) else put("error", error)
        put("timestamp", timestamp)
        put("signature", signature)
    }.toString()

    companion object {
        private const val MAX_CLOCK_SKEW_MILLIS = 2 * 60 * 1000L
        private const val MAX_NONCES = 256
    }
}

class PhoneHubServer(
    private val processor: PhoneHubRequestProcessor,
    private val onServerError: ((Throwable) -> Unit)? = null
) {
    private val running = AtomicBoolean(false)
    @Volatile
    private var serverSocket: ServerSocket? = null

    fun start() {
        if (!running.compareAndSet(false, true)) return
        thread(name = "PhoneHubServer", isDaemon = true) {
            try {
                val socket = ServerSocket().apply {
                    reuseAddress = true
                    bind(InetSocketAddress("0.0.0.0", PORT))
                }
                serverSocket = socket
                while (running.get()) {
                    val client = try {
                        socket.accept()
                    } catch (e: SocketException) {
                        if (running.get()) throw e else break
                    }
                    handleClient(client)
                }
            } catch (t: Throwable) {
                if (running.get()) onServerError?.invoke(t)
            } finally {
                running.set(false)
                try {
                    serverSocket?.close()
                } catch (_: Exception) {
                }
                serverSocket = null
            }
        }
    }

    fun stop() {
        running.set(false)
        try {
            serverSocket?.close()
        } catch (_: Exception) {
        }
    }

    fun isRunning(): Boolean = running.get()

    private fun handleClient(client: Socket) {
        thread(name = "PhoneHubClient", isDaemon = true) {
            client.use { socket ->
                socket.soTimeout = CLIENT_IDLE_TIMEOUT_MILLIS
                val reader = socket.getInputStream().bufferedReader()
                val writer = socket.getOutputStream().bufferedWriter()
                while (running.get()) {
                    val line = try {
                        reader.readLine()
                    } catch (_: Exception) {
                        null
                    } ?: break
                    val response = processor.process(line)
                    writer.write(response)
                    writer.newLine()
                    writer.flush()
                }
            }
        }
    }

    companion object {
        const val PORT = 8765
        private const val CLIENT_IDLE_TIMEOUT_MILLIS = 60_000
    }
}

private fun JsonPrimitive.intOrNullCompat(): Int? = try { int } catch (_: Exception) { null }
private fun JsonPrimitive.longOrNullCompat(): Long? = try { long } catch (_: Exception) { null }
private fun JsonPrimitive.contentOrNullCompat(): String? = try { content } catch (_: Exception) { null }
