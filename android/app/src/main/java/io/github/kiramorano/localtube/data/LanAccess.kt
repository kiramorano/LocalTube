package io.github.kiramorano.localtube.data

import android.content.Context
import java.net.Inet4Address
import java.net.NetworkInterface
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * Доступ к библиотеке из локальной сети.
 *
 * Модель повторяет настольную версию (access.py): шестизначный PIN, ключ
 * устройства как HMAC от PIN на случайном секрете, ограничение перебора. Отличие
 * одно: на телефоне нет «владельца по адресу 127.0.0.1» — сервер поднимается
 * ради других устройств, поэтому PIN спрашивается у всех гостей. Телефон в
 * чужой сети иначе раздавал бы библиотеку кому угодно.
 *
 * Ключ устройства не хранится: он пересчитывается на каждой проверке. Это даёт
 * бесплатную инвалидацию — смена PIN меняет и PIN, и секрет, и все ранее
 * впущенные устройства отключаются.
 */
class LanAccess(context: Context) {

    // Отдельный файл настроек: PIN и секрет не должны попадать в общий экспорт
    // настроек приложения.
    private val prefs = context.applicationContext
        .getSharedPreferences("localtube_access", Context.MODE_PRIVATE)

    private val lock = Any()

    /** Попытки ввода PIN: адрес -> (счётчик, начало окна). */
    private val attempts = HashMap<String, Pair<Int, Long>>()

    /** Текущий PIN. Создаётся при первом обращении и живёт до сброса. */
    val pin: String
        get() = synchronized(lock) { ensureState().first }

    /**
     * Секрет для HMAC. Наружу не отдаётся никогда: зная его и PIN, можно
     * подделать ключ устройства.
     */
    private val secret: String
        get() = synchronized(lock) { ensureState().second }

    private fun ensureState(): Pair<String, String> {
        val storedPin = prefs.getString(KEY_PIN, null)
        val storedSecret = prefs.getString(KEY_SECRET, null)
        // Кривой PIN (пустой, короткий, с буквами) заменяем новым: иначе гость
        // не смог бы войти вообще, а причина осталась бы невидимой.
        val pinOk = storedPin != null && storedPin.length == PIN_LENGTH && storedPin.all(Char::isDigit)
        val secretOk = !storedSecret.isNullOrBlank()
        if (pinOk && secretOk) return storedPin!! to storedSecret!!
        val newPin = if (pinOk) storedPin!! else randomPin()
        val newSecret = if (secretOk) storedSecret!! else randomSecret()
        prefs.edit().putString(KEY_PIN, newPin).putString(KEY_SECRET, newSecret).apply()
        return newPin to newSecret
    }

    /**
     * Новый PIN и новый секрет. Все впущенные устройства теряют доступ — это и
     * есть способ «выгнать всех», отдельного списка сессий нет.
     */
    fun regenerate(): String {
        synchronized(lock) {
            val newPin = randomPin()
            prefs.edit().putString(KEY_PIN, newPin).putString(KEY_SECRET, randomSecret()).apply()
            attempts.clear()
            return newPin
        }
    }

    /** Ключ устройства, который кладётся в cookie после верного PIN. */
    fun token(): String = hmac(secret, pin)

    fun isValidToken(token: String?): Boolean {
        val clean = asciiOrNull(token) ?: return false
        return constantTimeEquals(clean, token())
    }

    /**
     * Проверяет PIN с ограничением перебора.
     *
     * Шесть цифр — это миллион вариантов, а сервер отвечает сотни раз в секунду:
     * без ограничения полный перебор занимал бы минуты. Окно закрыто — сравнение
     * не выполняем вовсе, чтобы попытки его не продлевали.
     */
    fun checkPin(input: String?, address: String): PinResult {
        val clean = asciiOrNull(input)?.trim()
        synchronized(lock) {
            val now = System.currentTimeMillis()
            val record = attempts[address]
            val fresh = record != null && now - record.second < ATTEMPT_WINDOW_MS
            val used = if (fresh) record!!.first else 0
            if (used >= MAX_ATTEMPTS) {
                val waitMs = ATTEMPT_WINDOW_MS - (now - record!!.second)
                return PinResult.TooMany((waitMs / 1000).coerceAtLeast(1))
            }
            val expected = ensureState().first
            if (clean != null && constantTimeEquals(clean, expected)) {
                attempts.remove(address)
                return PinResult.Ok(hmac(ensureState().second, expected))
            }
            val start = if (fresh) record!!.second else now
            attempts[address] = (used + 1) to start
            return PinResult.Wrong(MAX_ATTEMPTS - used - 1)
        }
    }

    /** Результат проверки PIN. */
    sealed interface PinResult {
        /** PIN верный: token кладётся гостю в cookie. */
        data class Ok(val token: String) : PinResult

        /** PIN неверный, осталось столько попыток. */
        data class Wrong(val attemptsLeft: Int) : PinResult

        /** Попытки исчерпаны, ждать столько секунд. */
        data class TooMany(val retryAfterSec: Long) : PinResult
    }

    companion object {
        private const val KEY_PIN = "lan_pin"
        private const val KEY_SECRET = "lan_secret"

        const val PIN_LENGTH = 6
        const val MAX_ATTEMPTS = 10
        const val ATTEMPT_WINDOW_MS = 300_000L

        /** Имя cookie с ключом устройства. То же, что в веб-версии. */
        const val TOKEN_COOKIE = "lt_owner"

        /** Срок жизни cookie: гость не должен вводить PIN каждый вечер. */
        const val COOKIE_MAX_AGE_SEC = 90L * 24 * 3600

        private val random = java.security.SecureRandom()

        /** SecureRandom, а не Random: PIN открывает доступ к библиотеке. */
        internal fun randomPin(): String =
            (1..PIN_LENGTH).joinToString("") { random.nextInt(10).toString() }

        private fun randomSecret(): String {
            val bytes = ByteArray(32)
            random.nextBytes(bytes)
            return bytes.joinToString("") { "%02x".format(it) }
        }

        /** HMAC-SHA256 в hex: 64 символа. */
        internal fun hmac(secret: String, message: String): String {
            val mac = Mac.getInstance("HmacSHA256")
            mac.init(SecretKeySpec(secret.toByteArray(Charsets.UTF_8), "HmacSHA256"))
            return mac.doFinal(message.toByteArray(Charsets.UTF_8))
                .joinToString("") { "%02x".format(it) }
        }

        /**
         * Сравнение за постоянное время: обычное == выходит на первом же
         * несовпавшем символе, и время ответа подсказывало бы цифры PIN.
         */
        internal fun constantTimeEquals(a: String, b: String): Boolean {
            if (a.length != b.length) return false
            var diff = 0
            for (i in a.indices) diff = diff or (a[i].code xor b[i].code)
            return diff == 0
        }

        /**
         * Отсекает не-ASCII до сравнения. Кириллица в поле PIN на сервере давала
         * 500 внутри проверки доступа, то есть ломала вообще все страницы.
         */
        internal fun asciiOrNull(value: String?): String? {
            if (value == null) return null
            if (value.length > 64) return null
            return if (value.all { it.code in 32..126 }) value else null
        }

        /**
         * Адреса, по которым устройство видно из сети.
         *
         * Loopback не годится: по нему гость не подключится. Link-local
         * (169.254.x.x) тоже пропускаем — это признак того, что адрес не выдан.
         */
        fun localAddresses(): List<String> {
            val out = mutableListOf<String>()
            runCatching {
                NetworkInterface.getNetworkInterfaces()?.toList()?.forEach { iface ->
                    if (!iface.isUp || iface.isLoopback) return@forEach
                    iface.inetAddresses?.toList()?.forEach { addr ->
                        if (addr is Inet4Address && !addr.isLoopbackAddress &&
                            !addr.isLinkLocalAddress && !addr.isMulticastAddress
                        ) {
                            addr.hostAddress?.let { out += it }
                        }
                    }
                }
            }
            // Сначала обычные домашние сети: гость почти всегда в одной из них,
            // и первым в списке должен стоять адрес, который сработает.
            return out.distinct().sortedBy { if (it.startsWith("192.168.")) 0 else 1 }
        }

        fun urlFor(host: String, port: Int): String = "http://$host:$port"
    }
}
