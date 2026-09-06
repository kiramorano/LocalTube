package io.github.kiramorano.localtube.data

import android.media.audiofx.BassBoost
import android.media.audiofx.Equalizer

/**
 * Эквалайзер и усиление басов для плеера.
 *
 * В веб-версии это «Шакализатор» и «Улучшайзер» на Web Audio: девять
 * фильтров 60 Гц…14 кГц с набором пресетов. На Android аппаратный эквалайзер
 * даёт свои полосы (обычно пять), поэтому усиления пересчитываются по
 * центральным частотам, а не переносятся по индексу: иначе один и тот же пресет
 * звучал бы по-разному на разных устройствах.
 */
object AudioEffects {

    /** Пресеты и их усиления по частотам веб-версии, в децибелах. */
    enum class Preset(val id: String, val label: String, val gainsDb: List<Double>) {
        OFF("off", "Выключен", List(FREQUENCIES.size) { 0.0 }),
        BASS("bass", "Басы", listOf(7.0, 6.0, 4.0, 1.5, 0.0, 0.0, 0.0, 0.0, 0.0)),
        VOICE("voice", "Голос", listOf(-3.0, -2.0, 0.0, 3.0, 5.0, 4.0, 2.0, 0.0, -1.0)),
        TREBLE("treble", "Высокие", listOf(0.0, 0.0, 0.0, 0.0, 1.0, 3.0, 5.0, 6.0, 7.0)),
        ROCK("rock", "Рок", listOf(5.0, 3.0, -1.0, -2.0, 0.0, 2.0, 4.0, 5.0, 4.0)),
        POP("pop", "Поп", listOf(-1.0, 2.0, 4.0, 4.0, 2.0, 0.0, -1.0, -1.0, 0.0)),
        FLAT_LOUD("loud", "Громче", listOf(4.0, 4.0, 3.0, 3.0, 3.0, 3.0, 4.0, 4.0, 4.0)),
        SHAKAL("shakal", "Шакализатор", listOf(9.0, -6.0, 8.0, -7.0, 9.0, -6.0, 8.0, 9.0, 9.0));

        companion object {
            fun from(id: String?): Preset = entries.firstOrNull { it.id == id } ?: OFF
        }
    }

    /** Центральные частоты пресетов в герцах: те же, что в video.html. */
    val FREQUENCIES = listOf(60, 170, 350, 1000, 3500, 6000, 10000, 12000, 14000)

    /**
     * Усиление для полосы устройства по её центральной частоте.
     *
     * Между заданными точками значение интерполируется линейно по логарифму
     * частоты: полоса устройства на 230 Гц лежит между 170 и 350 Гц, и брать
     * ближайшую точку означало бы терять половину настройки.
     */
    internal fun gainForFrequency(preset: Preset, frequencyHz: Int): Double {
        if (preset == Preset.OFF) return 0.0
        val gains = preset.gainsDb
        if (frequencyHz <= FREQUENCIES.first()) return gains.first()
        if (frequencyHz >= FREQUENCIES.last()) return gains.last()
        for (i in 0 until FREQUENCIES.size - 1) {
            val low = FREQUENCIES[i]
            val high = FREQUENCIES[i + 1]
            if (frequencyHz in low..high) {
                // Логарифмическая шкала: слух воспринимает частоту именно так.
                val t = (Math.log(frequencyHz.toDouble()) - Math.log(low.toDouble())) /
                    (Math.log(high.toDouble()) - Math.log(low.toDouble()))
                return gains[i] + (gains[i + 1] - gains[i]) * t
            }
        }
        return 0.0
    }

    /**
     * Держит эффекты одного плеера. Создание Equalizer может бросить исключение
     * (нет аудиосессии, эффект занят другим приложением), поэтому все вызовы
     * защищены: отсутствие эквалайзера не должно ломать воспроизведение.
     */
    class Controller(audioSessionId: Int) {
        private var equalizer: Equalizer? = null
        private var bass: BassBoost? = null

        /** false, если устройство не дало создать эффекты. */
        val available: Boolean

        init {
            equalizer = runCatching { Equalizer(EFFECT_PRIORITY, audioSessionId) }.getOrNull()
            bass = runCatching { BassBoost(EFFECT_PRIORITY, audioSessionId) }.getOrNull()
            available = equalizer != null || bass != null
        }

        fun apply(preset: Preset, bassBoostMillibels: Int) {
            val eq = equalizer
            if (eq != null) {
                runCatching {
                    // Выключенный пресет именно выключает эффект, а не выставляет
                    // нули: иначе эквалайзер продолжал бы обрабатывать звук зря.
                    eq.enabled = preset != Preset.OFF
                    if (preset != Preset.OFF) {
                        val min = eq.bandLevelRange[0].toInt()
                        val max = eq.bandLevelRange[1].toInt()
                        for (band in 0 until eq.numberOfBands) {
                            // getCenterFreq отдаёт милигерцы.
                            val hz = eq.getCenterFreq(band.toShort()) / 1000
                            val millibels = (gainForFrequency(preset, hz) * 100).toInt()
                            eq.setBandLevel(band.toShort(), millibels.coerceIn(min, max).toShort())
                        }
                    }
                }
            }
            val bb = bass
            if (bb != null) {
                runCatching {
                    bb.enabled = bassBoostMillibels > 0
                    if (bassBoostMillibels > 0) {
                        bb.setStrength(bassBoostMillibels.coerceIn(0, 1000).toShort())
                    }
                }
            }
        }

        fun release() {
            runCatching { equalizer?.release() }
            runCatching { bass?.release() }
            equalizer = null
            bass = null
        }

        private companion object {
            /** Приоритет эффекта: 0 — обычное приложение. */
            const val EFFECT_PRIORITY = 0
        }
    }
}
