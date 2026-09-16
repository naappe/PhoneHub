package mv.phonehub.link

import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

object AuthProtocol {
    fun sign(secret: ByteArray, nonce: String, body: String): String {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(secret, "HmacSHA256"))
        val bytes = mac.doFinal("$nonce\n$body".toByteArray(Charsets.UTF_8))
        return bytes.joinToString("") { "%02x".format(it) }
    }

    fun verify(secret: ByteArray, nonce: String, body: String, signature: String): Boolean {
        val expected = sign(secret, nonce, body)
        if (expected.length != signature.length) return false

        var diff = 0
        for (i in expected.indices) {
            diff = diff or (expected[i].code xor signature[i].code)
        }
        return diff == 0
    }
}
