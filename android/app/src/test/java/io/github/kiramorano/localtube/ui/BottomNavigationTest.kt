package io.github.kiramorano.localtube.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Нижняя навигация: подсветка пункта и состав панели.
 *
 * Причина этих проверок — подсветка сравнивалась строгим равенством маршрута,
 * поэтому на вложенных экранах (плейлисты, история, поиск) не был выделен ни
 * один пункт: панель показывала, будто приложение нигде не находится.
 */
class BottomNavigationTest {

    @Test
    fun `на своём маршруте пункт подсвечен`() {
        for (tab in bottomTabs) {
            assertTrue("«${tab.label}» не подсвечен на ${tab.route}", tab.matches(tab.route))
        }
    }

    @Test
    fun `в каждом разделе подсвечен ровно один пункт`() {
        // Два подсвеченных пункта сбивают с толку не меньше, чем ни одного.
        val routes = bottomTabs.flatMap { listOf(it.route) + it.childRoutes }
        for (route in routes) {
            val hits = bottomTabs.count { it.matches(route) }
            assertEquals("маршрут $route подсвечивает $hits пунктов", 1, hits)
        }
    }

    @Test
    fun `вложенные разделы подсвечивают родительский пункт`() {
        val marked = { route: String -> bottomTabs.firstOrNull { it.matches(route) }?.label }
        assertEquals("Избранное", marked("history"))
        assertEquals("Моё", marked("collections"))
        assertEquals("Моё", marked("collection/{collectionId}"))
    }

    @Test
    fun `маршруты панели не пересекаются`() {
        // Один и тот же экран не может принадлежать двум пунктам.
        val all = bottomTabs.flatMap { listOf(it.route) + it.childRoutes }
        assertEquals("маршруты дублируются: $all", all.size, all.toSet().size)
    }

    @Test
    fun `вне панели подсветки нет`() {
        // Настройки открываются из шапки, а не из панели: подсвечивать нечего.
        for (route in listOf("settings", "search", "subtitles/{videoId}", null)) {
            assertEquals(
                "маршрут $route зря подсвечивает пункт",
                0,
                bottomTabs.count { it.matches(route) }
            )
        }
    }

    @Test
    fun `полноэкранные разделы не подсвечивают пункты панели`() {
        // На плеере и в ленте Shorts панели нет вообще.
        for (route in fullScreenRoutes) {
            assertEquals(
                "полноэкранный $route подсвечивает пункт панели",
                0,
                bottomTabs.count { it.matches(route) }
            )
        }
    }

    @Test
    fun `в панели пять пунктов`() {
        // Шестой не влезает: на экране 320dp подпись «Избранное» обрезается уже
        // при пяти. Материал тоже ограничивает панель пятью пунктами.
        assertTrue("пунктов ${bottomTabs.size}, больше пяти не влезет", bottomTabs.size <= 5)
        assertTrue("панель почти пустая", bottomTabs.size >= 3)
    }

    @Test
    fun `у пунктов разные иконки для выбранного и обычного состояния`() {
        // Отличие только цветом было почти незаметно; заливная иконка против
        // контурной — второй независимый признак.
        for (tab in bottomTabs) {
            assertNotEquals(
                "«${tab.label}»: иконка не меняется в выбранном состоянии",
                tab.icon,
                tab.iconOutlined
            )
        }
    }

    @Test
    fun `подписи заданы и коротки`() {
        for (tab in bottomTabs) {
            assertFalse("пункт ${tab.route} без подписи", tab.label.isBlank())
            // На пятую часть экрана 360dp приходится 72dp: длинная подпись
            // всё равно обрежется, и пункт станет неотличим от соседнего.
            assertTrue(
                "подпись «${tab.label}» слишком длинная для узкого экрана",
                tab.label.length <= 10
            )
        }
    }

    @Test
    fun `панель начинается с главной`() {
        // Первый пункт — начальный экран NavHost: иначе при запуске подсветка
        // стоит не там, где пользователь оказался.
        assertEquals("home", bottomTabs.first().route)
    }
}
