package io.github.kiramorano.localtube.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Тесты выбора задачи из очереди и сортировки каталога — логика, которую можно
 * проверить без Android-окружения.
 */
class QueueOrderTest {

    private fun task(
        id: String,
        priority: TaskPriority = TaskPriority.NORMAL,
        addedAt: Long = 0,
        status: TaskStatus = TaskStatus.WAITING
    ) = DownloadTask(
        id = id, title = id, url = "u", formatId = "best",
        status = status, progress = 0f, addedAt = addedAt, error = null,
        priority = priority
    )

    /** Тот же порядок, что применяет воркер очереди. */
    private fun next(tasks: List<DownloadTask>): DownloadTask? = tasks
        .filter { it.status == TaskStatus.WAITING }
        .minWithOrNull(compareBy({ it.priority.order }, { it.addedAt }))

    @Test
    fun `high priority goes first`() {
        val chosen = next(
            listOf(
                task("a", TaskPriority.NORMAL, 1),
                task("b", TaskPriority.HIGH, 2),
                task("c", TaskPriority.LOW, 3)
            )
        )
        assertEquals("b", chosen?.id)
    }

    @Test
    fun `low priority goes last`() {
        val chosen = next(
            listOf(
                task("low", TaskPriority.LOW, 1),
                task("normal", TaskPriority.NORMAL, 2)
            )
        )
        assertEquals("normal", chosen?.id)
    }

    @Test
    fun `equal priority keeps insertion order`() {
        val chosen = next(
            listOf(
                task("second", TaskPriority.NORMAL, 200),
                task("first", TaskPriority.NORMAL, 100)
            )
        )
        assertEquals("first", chosen?.id)
    }

    @Test
    fun `finished tasks are not picked`() {
        val chosen = next(
            listOf(
                task("done", status = TaskStatus.COMPLETED),
                task("failed", status = TaskStatus.ERROR),
                task("canceled", status = TaskStatus.CANCELED)
            )
        )
        assertNull(chosen)
    }

    @Test
    fun `isFinished covers terminal states`() {
        assertTrue(task("a", status = TaskStatus.COMPLETED).isFinished)
        assertTrue(task("a", status = TaskStatus.ERROR).isFinished)
        assertTrue(task("a", status = TaskStatus.CANCELED).isFinished)
        assertTrue(!task("a", status = TaskStatus.WAITING).isFinished)
        assertTrue(!task("a", status = TaskStatus.DOWNLOADING).isFinished)
    }

    @Test
    fun `status text shows speed and eta while downloading`() {
        val t = task("a", status = TaskStatus.DOWNLOADING).copy(
            status = TaskStatus.DOWNLOADING, progress = 42f, speed = "1.5MiB/s", etaSeconds = 90
        )
        val text = t.statusText
        assertTrue(text.contains("42"))
        assertTrue(text.contains("1.5MiB/s"))
        assertTrue("ETA должна быть в минутах", text.contains("1м"))
    }

    @Test
    fun `priority order values are distinct and ascending`() {
        assertEquals(0, TaskPriority.HIGH.order)
        assertEquals(1, TaskPriority.NORMAL.order)
        assertEquals(2, TaskPriority.LOW.order)
    }
}

class CatalogSortTest {

    private fun video(
        id: String,
        title: String = id,
        uploadDate: String = "",
        addedAt: String = "",
        sizeMb: Double = 0.0
    ) = VideoItem(
        id = id, title = title, author = "A", thumb = null, videoPath = null,
        sizeMb = sizeMb, isShort = false, source = "youtube",
        addedAt = addedAt, uploadDate = uploadDate
    )

    @Test
    fun `sort key prefers upload date`() {
        val v = video("a", uploadDate = "20240101", addedAt = "2020-01-01 00:00")
        assertEquals("20240101", v.sortKey)
    }

    @Test
    fun `sort key falls back to added date`() {
        val v = video("a", addedAt = "2026-05-05 10:00")
        assertEquals("2026-05-05 10:00", v.sortKey)
    }

    @Test
    fun `newest first`() {
        val list = listOf(
            video("old", uploadDate = "20200101"),
            video("new", uploadDate = "20260101")
        ).sortedByDescending { it.sortKey }
        assertEquals("new", list.first().id)
    }

    @Test
    fun `theme resolves by id and falls back to dark`() {
        assertEquals(AppTheme.AERO, AppTheme.from("aero"))
        assertEquals(AppTheme.LIGHT, AppTheme.from("light"))
        assertEquals(AppTheme.DARK, AppTheme.from("nonsense"))
        assertEquals(AppTheme.DARK, AppTheme.from(null))
    }

    @Test
    fun `catalog sort resolves by id`() {
        assertEquals(CatalogSort.TITLE, CatalogSort.from("title"))
        assertEquals(CatalogSort.NEWEST, CatalogSort.from(null))
    }
}
