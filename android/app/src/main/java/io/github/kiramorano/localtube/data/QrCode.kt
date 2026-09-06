package io.github.kiramorano.localtube.data

import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel

/**
 * QR-код с адресом раздачи.
 *
 * На телефоне это основной способ передать адрес: набирать «192.168.1.42:8733»
 * руками на чужом устройстве неудобно. В веб-версии ту же роль играет
 * access.make_qr_png (access.py).
 *
 * Класс не знает про Android: кодирование возвращает матрицу точек, а картинку
 * из неё собирает интерфейс. Так логику можно проверить обычным unit-тестом,
 * без эмулятора.
 */
object QrCode {

    /** Уровень коррекции M, как error='m' у segno на сервере. */
    private val HINTS = mapOf<EncodeHintType, Any>(
        EncodeHintType.ERROR_CORRECTION to ErrorCorrectionLevel.M,
        EncodeHintType.CHARACTER_SET to "UTF-8",
        // Рамку рисуем сами: своя ширина отступа предсказуемее, чем поведение
        // библиотеки при масштабировании.
        EncodeHintType.MARGIN to 0
    )

    /**
     * Матрица кода: `true` — тёмная точка.
     *
     * @param border ширина светлого поля в точках. Без него код не читается:
     *   сканеру нужна свободная зона вокруг.
     */
    fun matrix(text: String, border: Int = 2): Array<BooleanArray> {
        require(text.isNotBlank()) { "Пустую строку кодировать нечего" }
        val safeBorder = border.coerceIn(0, 8)
        val bits = QRCodeWriter().encode(text, BarcodeFormat.QR_CODE, 0, 0, HINTS)
        val size = bits.width + safeBorder * 2
        return Array(size) { y ->
            BooleanArray(size) { x ->
                val innerX = x - safeBorder
                val innerY = y - safeBorder
                if (innerX < 0 || innerY < 0 || innerX >= bits.width || innerY >= bits.height) {
                    false
                } else {
                    bits.get(innerX, innerY)
                }
            }
        }
    }
}
