package io.github.kiramorano.localtube.ui

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import androidx.core.content.res.ResourcesCompat
import androidx.test.core.app.ApplicationProvider
import io.github.kiramorano.localtube.R
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/**
 * Отрисовка иконок в пиксели.
 *
 * Тест пропорций (VectorIconRatioTest) читает только атрибуты XML. Здесь знак
 * реально рисуется и проверяется по пикселям: растянут он или нет, и виден ли
 * треугольник play. Пропорции можно было бы объявить верно и всё равно
 * получить кашу — например если контур не влезает в вьюпорт.
 *
 * Robolectric с API 33 рисует настоящим Skia, поэтому цвета пикселей настоящие.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33])
// Без NATIVE Robolectric подменяет Canvas заглушками: рисование проходит без
// ошибок, но битмап остаётся пустым, и тест ничего не проверяет.
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class VectorIconRenderTest {

    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()

    private fun drawable(resId: Int) =
        ResourcesCompat.getDrawable(context.resources, resId, null)
            ?: throw AssertionError("ресурс не разобран: $resId")

    private fun render(resId: Int, width: Int, height: Int): Bitmap {
        val drawable = drawable(resId)
        val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        drawable.setBounds(0, 0, width, height)
        drawable.draw(Canvas(bitmap))
        return bitmap
    }

    /**
     * Отрисовка в размер, который ресурс сообщает о себе сам.
     *
     * Именно так знак попадает на экран: Compose измеряет картинку по
     * intrinsic-размеру, а ContentScale.Fit сохраняет пропорции этого размера.
     * Если рисовать в заданные извне bounds, искажение из ic_logo.xml не
     * воспроизведётся, и тест пройдёт мимо той самой поломки.
     */
    private fun renderIntrinsic(resId: Int, scale: Int = 10): Bitmap {
        val drawable = drawable(resId)
        val width = drawable.intrinsicWidth * scale
        val height = drawable.intrinsicHeight * scale
        assertTrue("нет intrinsic-размера", width > 0 && height > 0)
        val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        drawable.setBounds(0, 0, width, height)
        drawable.draw(Canvas(bitmap))
        return bitmap
    }

    /** Границы непрозрачных пикселей: left, top, right, bottom. */
    private fun opaqueBounds(bitmap: Bitmap): IntArray {
        var left = bitmap.width
        var top = bitmap.height
        var right = -1
        var bottom = -1
        for (y in 0 until bitmap.height) {
            for (x in 0 until bitmap.width) {
                if (Color.alpha(bitmap.getPixel(x, y)) > 8) {
                    if (x < left) left = x
                    if (x > right) right = x
                    if (y < top) top = y
                    if (y > bottom) bottom = y
                }
            }
        }
        assertTrue("ничего не нарисовано", right >= 0)
        return intArrayOf(left, top, right, bottom)
    }

    @Test
    fun `логотип рисуется в тех же пропорциях, что в вебе`() {
        // Контур занимает 20 из 24 единиц по ширине и 14 из 24 по высоте, то
        // есть отношение ширины к высоте 20/14 ≈ 1.43. При width 30dp /
        // height 20dp знак растягивался, и отношение уезжало к 2.14.
        //
        // Рисуем в intrinsic-размер: именно его берёт Compose, и только так
        // растяжение из ic_logo.xml вообще воспроизводится.
        val bitmap = renderIntrinsic(R.drawable.ic_logo)
        val (left, top, right, bottom) = opaqueBounds(bitmap).toList()

        val ratio = (right - left + 1).toDouble() / (bottom - top + 1).toDouble()
        assertEquals("пропорции знака", 20.0 / 14.0, ratio, 0.06)
    }

    @Test
    fun `логотип красный и с прозрачным треугольником play`() {
        val bitmap = render(R.drawable.ic_logo, 240, 240)

        // Центр плашки левее середины — там заливка.
        val body = bitmap.getPixel(60, 120)
        assertEquals("красная заливка", Color.RED, body)

        // Треугольник play — вырез в заливке, а не белая фигура поверх: только
        // так знак сохраняется при монохромном тонировании Android 13+.
        // В координатах вьюпорта его середина около (12, 12) из 24.
        val hole = bitmap.getPixel(120, 120)
        assertEquals("треугольник прозрачный", 0, Color.alpha(hole))
    }

    @Test
    fun `иконка приложения не выходит из safe zone`() {
        // Adaptive icon маскируется: гарантированно видна только центральная
        // окружность диаметром 66 из 108. Прежняя плашка занимала x 20..88, её
        // углы отстояли от центра на 39 при допустимых 33, и срезались.
        val size = 216 // 108dp при 2x, чтобы считать в целых пикселях
        val bitmap = render(R.drawable.ic_launcher_foreground, size, size)
        val (left, top, right, bottom) = opaqueBounds(bitmap).toList()

        val cx = size / 2.0
        val cy = size / 2.0
        val safeRadius = size * 66.0 / 108.0 / 2.0
        listOf(
            left to top, right to top, left to bottom, right to bottom
        ).forEach { (x, y) ->
            val dx = x - cx
            val dy = y - cy
            val distance = Math.sqrt(dx * dx + dy * dy)
            assertTrue(
                "угол ($x, $y) выходит из safe zone: $distance > $safeRadius",
                distance <= safeRadius
            )
        }
    }

    @Test
    fun `иконка приложения нарисована по центру`() {
        val size = 216
        val bitmap = render(R.drawable.ic_launcher_foreground, size, size)
        val (left, top, right, bottom) = opaqueBounds(bitmap).toList()

        // Отступы слева и справа равны, сверху и снизу тоже: знак не съехал.
        assertEquals("по горизонтали", left.toDouble(), (size - 1 - right).toDouble(), 2.0)
        assertEquals("по вертикали", top.toDouble(), (size - 1 - bottom).toDouble(), 2.0)
    }

    @Test
    fun `тв-баннер заливает фон и рисует знак по центру`() {
        val bitmap = render(R.drawable.tv_banner, 320, 180)

        // Фон непрозрачный: на лончере ТВ баннер лежит на чужой подложке.
        assertEquals(255, Color.alpha(bitmap.getPixel(4, 4)))

        // Знак по центру канвы: проверяем красный пиксель слева от выреза.
        assertEquals(Color.RED, bitmap.getPixel(125, 90))
    }
}
