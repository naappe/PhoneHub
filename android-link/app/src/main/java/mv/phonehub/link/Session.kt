package mv.phonehub.link

import java.security.SecureRandom

private val secureRandom = SecureRandom()

fun createRoomCode(): String = "%06d".format(secureRandom.nextInt(1_000_000))
