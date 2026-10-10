package io.github.kiramorano.localtube.data

import androidx.test.core.app.ApplicationProvider
import io.github.kiramorano.localtube.LocalTubeApp
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Постановка оформления канала в общую очередь загрузок.
 *
 * Проверяется через реальный DownloadManager, а не конструктор DownloadTask:
 * важна именно дедупликация и попадание элемента в tasks, то есть в тот список,
 * который рисует экран загрузок.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33])
class ChannelAssetsQueueTest {

    private val app: LocalTubeApp = ApplicationProvider.getApplicationContext()

    private val downloads get() = app.repository.downloads

    private val author = "Канал Для Очереди"
    private val url = "https://www.youtube.com/@autotest"

    @Before
    fun clean() {
        downloads.setPaused(true)
        downloads.tasks.value.forEach { downloads.remove(it.id) }
    }

    @Test
    fun `оформление попадает в очередь видимым элементом`() {
        val id = downloads.addChannelAssets(author, url)

        val task = downloads.tasks.value.firstOrNull { it.id == id }
        assertNotNull("задачи нет в очереди", task)
        assertEquals(TaskKind.CHANNEL_ASSETS, task!!.kind)
        assertEquals(author, task.author)
        // Заголовок обязан называть канал: в очереди видно только его.
        assertTrue(task.title, task.title.contains(author))
    }

    @Test
    fun `повторная постановка не плодит дубли`() {
        // Экран канала дёргает загрузку при каждом открытии, и без защиты
        // очередь наполнялась бы одинаковыми задачами.
        val first = downloads.addChannelAssets(author, url)
        val second = downloads.addChannelAssets(author, url)

        assertEquals(first, second)
        val count = downloads.tasks.value.count {
            it.kind == TaskKind.CHANNEL_ASSETS && it.author == author
        }
        assertEquals(1, count)
    }

    @Test
    fun `разные каналы получают разные задачи`() {
        val a = downloads.addChannelAssets("Первый", url)
        val b = downloads.addChannelAssets("Второй", url)

        assertTrue("id совпали", a != b)
        assertEquals(2, downloads.tasks.value.count { it.kind == TaskKind.CHANNEL_ASSETS })
    }

    @Test
    fun `завершённая задача не мешает поставить новую`() {
        // Дедупликация смотрит только на незавершённые: обновить оформление
        // повторно должно быть можно.
        val first = downloads.addChannelAssets(author, url)
        downloads.cancel(first)

        val second = downloads.addChannelAssets(author, url)
        assertTrue("новая задача не создана", first != second)
    }

    @Test
    fun `оформление можно убрать из очереди`() {
        val id = downloads.addChannelAssets(author, url)
        downloads.remove(id)

        assertNull(downloads.tasks.value.firstOrNull { it.id == id })
    }

    @Test
    fun `без адреса канала задача не ставится`() {
        // queueAssets возвращает null, если адрес неизвестен: пустая задача в
        // очереди сразу упала бы с ошибкой и только мешала.
        val id = app.repository.channels.queueAssets("Канал Без Адреса", channelUrl = null)

        assertNull(id)
        assertTrue(downloads.tasks.value.none { it.author == "Канал Без Адреса" })
    }

    @Test
    fun `queueAssets ставит задачу по переданному адресу`() {
        val id = app.repository.channels.queueAssets(author, url)

        assertNotNull(id)
        val task = downloads.tasks.value.firstOrNull { it.id == id }
        assertEquals(TaskKind.CHANNEL_ASSETS, task?.kind)
        assertEquals(url, task?.url)
    }
}
