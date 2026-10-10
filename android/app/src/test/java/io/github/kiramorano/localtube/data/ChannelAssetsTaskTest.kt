package io.github.kiramorano.localtube.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Задача оформления канала в очереди загрузок.
 *
 * Раньше аватарка, шапка и описание канала грузились молча в стороннем scope:
 * пользователь не видел ни того, что работа идёт, ни того, что она сорвалась.
 * Теперь это такой же элемент очереди, как видео, но со своим исполнителем —
 * без формата, склейки и процентов от yt-dlp. Тесты закрепляют отличия модели,
 * из-за которых очередь могла бы показать бессмысленное «Скачивание 0%» или
 * предложить приоритет, ни на что не влияющий.
 */
class ChannelAssetsTaskTest {

    private fun assetsTask(
        status: TaskStatus = TaskStatus.WAITING,
        progress: Float = 0f,
        author: String = "Автор Канала"
    ) = DownloadTask(
        id = "a1",
        title = "Оформление канала: $author",
        url = "https://www.youtube.com/@autotest",
        formatId = "",
        status = status,
        progress = progress,
        addedAt = 0,
        error = null,
        kind = TaskKind.CHANNEL_ASSETS,
        author = author
    )

    @Test
    fun `видео остаётся видом по умолчанию`() {
        // Очередь, записанная до появления оформления, не содержит поля kind:
        // дефолт обязан оставаться видео, иначе старые задачи после обновления
        // ушли бы не тому исполнителю.
        val video = DownloadTask(
            id = "v1", title = "Ролик", url = "u", formatId = "best",
            status = TaskStatus.WAITING, progress = 0f, addedAt = 0, error = null
        )
        assertEquals(TaskKind.VIDEO, video.kind)
        assertEquals("", video.author)
    }

    @Test
    fun `оформление не показывает проценты вместо шага`() {
        // Прогресс шаговый (0 → 34 → 67), и «Скачивание 0%» на запросе
        // метаданных выглядело бы зависшей задачей.
        val text = assetsTask(TaskStatus.DOWNLOADING, progress = 0f).statusText
        assertFalse("проценты не нужны: $text", text.contains("%"))
        assertEquals("Запрос данных канала", text)
    }

    @Test
    fun `шаги оформления называются понятно`() {
        assertEquals(
            "Запрос данных канала",
            assetsTask(TaskStatus.DOWNLOADING, 0f).statusText
        )
        assertEquals("Аватарка", assetsTask(TaskStatus.DOWNLOADING, 34f).statusText)
        assertEquals("Шапка канала", assetsTask(TaskStatus.DOWNLOADING, 67f).statusText)
    }

    @Test
    fun `видео по-прежнему показывает проценты скорость и остаток`() {
        // Ветка по типу задачи не должна была задеть обычную загрузку.
        val video = DownloadTask(
            id = "v1", title = "Ролик", url = "u", formatId = "best",
            status = TaskStatus.DOWNLOADING, progress = 42f, addedAt = 0, error = null,
            speed = "1.5MiB/s", etaSeconds = 65
        )
        val text = video.statusText
        assertTrue(text, text.contains("42"))
        assertTrue(text, text.contains("1.5MiB/s"))
    }

    @Test
    fun `приоритет не предлагается для оформления`() {
        // У оформления свой исполнитель, в общем порядке воркера он не
        // участвует: чип приоритета обещал бы настройку, которая ничего не даёт.
        assertFalse(assetsTask().supportsPriority)
        val video = DownloadTask(
            id = "v1", title = "Ролик", url = "u", formatId = "best",
            status = TaskStatus.WAITING, progress = 0f, addedAt = 0, error = null
        )
        assertTrue(video.supportsPriority)
    }

    @Test
    fun `завершённое оформление отчитывается как готовое`() {
        val done = assetsTask(TaskStatus.COMPLETED, 100f)
        assertEquals("Готово", done.statusText)
        assertTrue(done.isFinished)
    }

    @Test
    fun `ошибка оформления показывает причину`() {
        val failed = assetsTask(TaskStatus.ERROR).copy(error = "yt-dlp: канал не найден")
        assertTrue(failed.statusText, failed.statusText.contains("канал не найден"))
        assertTrue(failed.isFinished)
    }

    @Test
    fun `заголовок задачи называет канал`() {
        // Заголовок — единственное, что видно в очереди: без имени канала
        // элемент был бы неотличим от соседнего.
        val task = assetsTask(author = "Кто-то")
        assertTrue(task.title, task.title.contains("Кто-то"))
        assertEquals("Кто-то", task.author)
    }
}
