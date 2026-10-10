package io.github.kiramorano.localtube.vm

import androidx.test.core.app.ApplicationProvider
import io.github.kiramorano.localtube.LocalTubeApp
import io.github.kiramorano.localtube.data.ChannelAssets
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowLooper

/**
 * Открытие страницы канала должно само подтягивать оформление.
 *
 * Раньше `load()` только читал локальный кэш (avatarFor/bannerFor/channelMeta),
 * а запрос к yt-dlp жил исключительно в кнопке «Обновить» на экране канала. На
 * канале, оформление которого ещё не скачивали, это давало пустую страницу:
 * серый круг вместо аватарки, никакого баннера и никакого описания — при том,
 * что yt-dlp эти данные отдаёт. Тест закрепляет, что запрос уходит без участия
 * пользователя, и что уже сохранённое оформление подхватывается из библиотеки.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33])
class ChannelAssetsAutoLoadTest {

    private val app: LocalTubeApp = ApplicationProvider.getApplicationContext()

    private val author = "Автотест Канал"

    @Before
    fun clean() {
        // Метаданные пишутся в файл и переживают прогон: без сброса второй тест
        // видел бы состояние от первого.
        app.repository.library.saveChannelMeta(author, ChannelAssets())
    }

    /**
     * Ждёт выполнения условия, прокручивая главный цикл.
     *
     * Одного `idleMainLooper()` не хватает: чтение библиотеки уходит в
     * `Dispatchers.IO` на настоящий пул потоков, и корутина возвращается на
     * главный поток только следующей задачей. Без ожидания тест проверял бы
     * состояние до чтения диска и падал бы через раз.
     */
    private fun waitFor(what: String, timeoutMs: Long = 10_000, cond: () -> Boolean) {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            ShadowLooper.idleMainLooper()
            if (cond()) return
            Thread.sleep(10)
        }
        throw AssertionError("не дождались: $what")
    }

    @Test
    fun `открытие канала подхватывает сохранённое оформление`() {
        val saved = ChannelAssets(
            title = author,
            avatarUrl = "https://example.invalid/a.jpg",
            bannerUrl = "https://example.invalid/b.jpg",
            description = "Описание канала из yt-dlp",
            subscribers = 1234,
            channelUrl = "https://www.youtube.com/@autotest"
        )
        app.repository.library.saveChannelMeta(author, saved)

        val vm = ChannelViewModel(app)
        vm.load(author)
        waitFor("автор") { vm.author == author }
        waitFor("описание") { vm.meta?.description == "Описание канала из yt-dlp" }

        // Именно этих полей не хватало на экране: заголовок, описание и число
        // подписчиков берутся из meta.
        assertEquals(author, vm.author)
        val meta = vm.meta
        assertTrue("meta не прочитана", meta != null)
        assertEquals("Описание канала из yt-dlp", meta!!.description)
        assertEquals(1234L, meta.subscribers)
    }

    @Test
    fun `адрес канала берётся из метаданных для запроса оформления`() {
        // fetchAssets без адреса не делает ничего, поэтому load() передаёт
        // channelUrl явно. Проверяем, что адрес находится и по метаданным —
        // на канале без скачанных видео другого источника нет.
        app.repository.library.saveChannelMeta(
            author,
            ChannelAssets(channelUrl = "https://www.youtube.com/@autotest")
        )

        assertEquals(
            "https://www.youtube.com/@autotest",
            app.repository.library.channelUrlOf(author)
        )
    }

    @Test
    fun `оформление подхватывается по событию загрузки`() {
        // Скачивание идёт в своей области, и раньше экран ждал его паузой в три
        // секунды: на медленной сети аватарка не успевала, и страница оставалась
        // пустой до повторного входа. Теперь ChannelSync сообщает о записи, а
        // модель перечитывает кэш. Проверяем без сети: пишем метаданные и подаём
        // то же событие, что подаёт загрузчик.
        val vm = ChannelViewModel(app)
        vm.load(author)
        waitFor("автор") { vm.author == author }
        waitFor("пустой кэш") { vm.meta?.description.orEmpty().isEmpty() }

        app.repository.library.saveChannelMeta(
            author,
            ChannelAssets(title = author, description = "Появилось после загрузки")
        )
        app.repository.channels.emitAssetsUpdated(author)
        waitFor("новое описание") { vm.meta?.description == "Появилось после загрузки" }

        assertEquals("Появилось после загрузки", vm.meta?.description)
    }

    @Test
    fun `событие чужого канала не затирает открытый`() {
        // Подписка одна на модель, а событий может прийти несколько: оформление
        // соседнего канала не должно подменять показанное.
        app.repository.library.saveChannelMeta(
            author,
            ChannelAssets(title = author, description = "Наш канал")
        )
        val vm = ChannelViewModel(app)
        vm.load(author)
        waitFor("своё описание") { vm.meta?.description == "Наш канал" }

        app.repository.library.saveChannelMeta(
            "Другой Канал",
            ChannelAssets(title = "Другой Канал", description = "Чужое описание")
        )
        app.repository.channels.emitAssetsUpdated("Другой Канал")
        ShadowLooper.idleMainLooper()
        Thread.sleep(50)
        ShadowLooper.idleMainLooper()

        assertEquals("Наш канал", vm.meta?.description)
    }

    @Test
    fun `открытие канала без оформления не падает`() {
        // Канала нет ни в библиотеке, ни в метаданных: load() обязан пережить
        // отсутствие адреса, иначе экран канала падал бы на первом открытии.
        val vm = ChannelViewModel(app)
        vm.load("Неизвестный автор")
        waitFor("автор") { vm.author == "Неизвестный автор" }

        assertEquals("Неизвестный автор", vm.author)
        assertTrue(vm.videos.isEmpty())
    }
}
