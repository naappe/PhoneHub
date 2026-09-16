package mv.phonehub.link

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec


data class PairedClient(
    val pcId: String,
    val secret: ByteArray,
    val pairedAtMillis: Long
)

class PairingStore(private val context: Context) {
    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    private var activePairingCode: String? = null
    private var activePairingExpiresAt: Long = 0L

    fun createPairingCode(): String {
        val code = generateHumanCode()
        activePairingCode = code
        activePairingExpiresAt = System.currentTimeMillis() + PAIRING_TTL_MILLIS
        return code
    }

    fun completePairing(pcId: String, pairingCode: String): PairedClient {
        val now = System.currentTimeMillis()
        val expected = activePairingCode
        require(expected != null && now <= activePairingExpiresAt) { "Pairing code expired" }
        require(pairingCode == expected) { "Pairing code is invalid" }
        require(pcId.isNotBlank()) { "PC id is required" }

        val secret = ByteArray(32).also { SecureRandom().nextBytes(it) }
        val encrypted = encryptSecret(secret)

        prefs.edit()
            .putString(KEY_PC_ID, pcId)
            .putLong(KEY_PAIRED_AT, now)
            .putString(KEY_SECRET_IV, Base64.encodeToString(encrypted.iv, Base64.NO_WRAP))
            .putString(KEY_SECRET_DATA, Base64.encodeToString(encrypted.ciphertext, Base64.NO_WRAP))
            .apply()

        activePairingCode = null
        activePairingExpiresAt = 0L
        return PairedClient(pcId = pcId, secret = secret, pairedAtMillis = now)
    }

    fun getPairedClient(): PairedClient? {
        val pcId = prefs.getString(KEY_PC_ID, null) ?: return null
        val ivText = prefs.getString(KEY_SECRET_IV, null) ?: return null
        val dataText = prefs.getString(KEY_SECRET_DATA, null) ?: return null
        val pairedAt = prefs.getLong(KEY_PAIRED_AT, 0L)

        return try {
            val secret = decryptSecret(
                iv = Base64.decode(ivText, Base64.NO_WRAP),
                ciphertext = Base64.decode(dataText, Base64.NO_WRAP)
            )
            PairedClient(pcId = pcId, secret = secret, pairedAtMillis = pairedAt)
        } catch (_: Exception) {
            null
        }
    }

    fun revokePairing() {
        prefs.edit().clear().apply()
        activePairingCode = null
        activePairingExpiresAt = 0L
        val keyStore = loadKeyStore()
        if (keyStore.containsAlias(KEYSTORE_ALIAS)) {
            keyStore.deleteEntry(KEYSTORE_ALIAS)
        }
    }

    private fun encryptSecret(secret: ByteArray): EncryptedSecret {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateWrappingKey())
        return EncryptedSecret(iv = cipher.iv, ciphertext = cipher.doFinal(secret))
    }

    private fun decryptSecret(iv: ByteArray, ciphertext: ByteArray): ByteArray {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, getOrCreateWrappingKey(), GCMParameterSpec(128, iv))
        return cipher.doFinal(ciphertext)
    }

    private fun getOrCreateWrappingKey(): SecretKey {
        val keyStore = loadKeyStore()
        (keyStore.getKey(KEYSTORE_ALIAS, null) as? SecretKey)?.let { return it }

        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
        val spec = KeyGenParameterSpec.Builder(
            KEYSTORE_ALIAS,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
        )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setRandomizedEncryptionRequired(true)
            .build()
        generator.init(spec)
        return generator.generateKey()
    }

    private fun loadKeyStore(): KeyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }

    private data class EncryptedSecret(val iv: ByteArray, val ciphertext: ByteArray)

    companion object {
        private const val PREFS_NAME = "phonehub_pairing"
        private const val KEY_PC_ID = "pc_id"
        private const val KEY_PAIRED_AT = "paired_at"
        private const val KEY_SECRET_IV = "secret_iv"
        private const val KEY_SECRET_DATA = "secret_data"
        private const val KEYSTORE_ALIAS = "phonehub_pairing_secret_v1"
        private const val ANDROID_KEYSTORE = "AndroidKeyStore"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
        private const val PAIRING_TTL_MILLIS = 5 * 60 * 1000L

        fun generateHumanCode(): String {
            val value = SecureRandom().nextInt(1_000_000)
            return value.toString().padStart(6, '0')
        }
    }
}
