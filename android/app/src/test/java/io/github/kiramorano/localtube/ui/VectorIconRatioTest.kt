package io.github.kiramorano.localtube.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Пропорции векторных иконок.
 *
 * Логотип в шапке был растянут по горизонтали в 1.5 раза: в ic_logo.xml стояло
 * width 30dp / height 20dp при вьюпорте 24 × 24. Числа были скопированы из
 * веб-CSS, где растяжения не возникает — у SVG действует preserveAspectRatio,
 * он вписывает вьюпорт. В Android так не выходит: Compose измеряет картинку по
 * intrinsic-размеру, а ContentScale.Fit сохраняет пропорции этого размера, а не
 * вьюпорта, поэтому Modifier.size() от искажения не спасал.
 *
 * Тест разбирает XML ресурсов напрямую, без Robolectric: нужны только объявленные
 * атрибуты, а не отрисовка.
 */
class VectorIconRatioTest {

    private val resDir = File("src/main/res")

    private fun attr(file: File, name: String): String {
        val text = file.readText()
        val match = Regex("""android:$name="([^"]+)"""").find(text)
        return requireNonNull(match, "$name в ${file.name}").groupValues[1]
    }

    private fun <T> requireNonNull(value: T?, what: String): T =
        value ?: throw AssertionError("не найдено: $what")

    private fun dp(value: String): Double = value.removeSuffix("dp").toDouble()

    /**
     * Пропорции intrinsic-размера обязаны совпадать с пропорциями вьюпорта:
     * иначе рисунок растянется, и никакой modifier это не исправит.
     */
    private fun assertRatioMatchesViewport(fileName: String) {
        val file = File(resDir, "drawable/$fileName")
        assertTrue("нет файла $fileName", file.isFile)

        val declared = dp(attr(file, "width")) / dp(attr(file, "height"))
        val viewport = attr(file, "viewportWidth").toDouble() /
            attr(file, "viewportHeight").toDouble()

        assertEquals(
            "$fileName: width/height ($declared) должно совпадать с вьюпортом ($viewport)",
            viewport,
            declared,
            0.001
        )
    }

    @Test
    fun `логотип не растянут`() {
        assertRatioMatchesViewport("ic_logo.xml")
    }

    @Test
    fun `иконка приложения не растянута`() {
        assertRatioMatchesViewport("ic_launcher_foreground.xml")
    }

    @Test
    fun `тв-баннер не растянут`() {
        assertRatioMatchesViewport("tv_banner.xml")
    }

    @Test
    fun `иконка приложения занимает всю канву 108dp`() {
        // Adaptive icon требует ровно 108 × 108: другой размер система масштабирует
        // сама, и рисунок уезжает из safe zone.
        val file = File(resDir, "drawable/ic_launcher_foreground.xml")
        assertEquals(108.0, dp(attr(file, "width")), 0.001)
        assertEquals(108.0, dp(attr(file, "height")), 0.001)
    }

    @Test
    fun `тв-баннер имеет соотношение 16 на 9`() {
        // Требование лончера Android TV.
        val file = File(resDir, "drawable/tv_banner.xml")
        assertEquals(
            16.0 / 9.0,
            dp(attr(file, "width")) / dp(attr(file, "height")),
            0.001
        )
    }

    @Test
    fun `логотип шапки, иконка и баннер рисуют один контур`() {
        // Иконка лончера была нарисована отдельной плашкой и не совпадала с
        // логотипом в шапке: на устройстве это выглядело как два разных продукта.
        val logo = pathData(File(resDir, "drawable/ic_logo.xml"))
        val launcher = pathData(File(resDir, "drawable/ic_launcher_foreground.xml"))
        val banner = pathData(File(resDir, "drawable/tv_banner.xml"))

        assertTrue("иконка повторяет логотип", launcher.contains(logo))
        assertTrue("баннер повторяет логотип", banner.contains(logo))
    }

    /** Самый длинный pathData в файле — это и есть контур знака. */
    private fun pathData(file: File): String =
        Regex("""android:pathData="([^"]+)"""")
            .findAll(file.readText())
            .map { it.groupValues[1] }
            .maxByOrNull { it.length }
            .orEmpty()

    @Test
    fun `круглая иконка объявлена в манифесте`() {
        // Ресурс ic_launcher_round существовал, но без android:roundIcon был
        // мёртвым файлом.
        val manifest = File("src/main/AndroidManifest.xml").readText()
        assertTrue(manifest.contains("android:roundIcon=\"@mipmap/ic_launcher_round\""))
        assertTrue(File(resDir, "mipmap-anydpi-v26/ic_launcher_round.xml").isFile)
    }
}
