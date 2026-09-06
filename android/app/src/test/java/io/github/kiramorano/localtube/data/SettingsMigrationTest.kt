package io.github.kiramorano.localtube.data

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * Разовый перенос настроек субтитров при обновлении приложения.
 *
 * Новое значение по умолчанию («не качать субтитры») помогает только чистой
 * установке: у всех, кто уже пользуется приложением, прежнее «ru,en» лежит в
 * SharedPreferences, и загрузка ломалась бы дальше. Проверяется и обратное — что
 * перенос не трогает языки, выставленные вручную.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33])
class SettingsMigrationTest {

    private val context = ApplicationProvider.getApplicationContext<Context>()

    private fun prefs() = context.getSharedPreferences("localtube", Context.MODE_PRIVATE)

    @Before
    fun clear() {
        prefs().edit().clear().commit()
    }

    @Test
    fun `прежние языки по умолчанию снимаются при обновлении`() {
        // Состояние установки до обновления.
        prefs().edit()
            .putString("sub_langs", Settings.LEGACY_SUB_LANGS)
            .putBoolean("download_subs", true)
            .commit()

        val settings = Settings(context)

        assertEquals("", settings.subLangs)
        assertFalse(settings.downloadSubs)
    }

    @Test
    fun `языки, выбранные пользователем, остаются`() {
        // «de» никогда не было значением по умолчанию: это осознанный выбор.
        prefs().edit()
            .putString("sub_langs", "de")
            .putBoolean("download_subs", true)
            .commit()

        val settings = Settings(context)

        assertEquals("de", settings.subLangs)
        assertTrue(settings.downloadSubs)
    }

    @Test
    fun `перенос выполняется один раз`() {
        prefs().edit()
            .putString("sub_langs", Settings.LEGACY_SUB_LANGS)
            .putBoolean("download_subs", true)
            .commit()
        Settings(context)

        // Пользователь снова захотел субтитры уже после обновления.
        Settings(context).apply {
            subLangs = "ru,en"
            downloadSubs = true
        }

        // Второй запуск не должен отбирать их обратно.
        val after = Settings(context)
        assertEquals("ru,en", after.subLangs)
        assertTrue(after.downloadSubs)
    }

    @Test
    fun `чистая установка получает пустые языки`() {
        val settings = Settings(context)

        assertEquals(Settings.DEFAULT_SUB_LANGS, settings.subLangs)
        assertEquals(Settings.DEFAULT_DOWNLOAD_SUBS, settings.downloadSubs)
        assertEquals(Settings.DEFAULT_AUDIO_LANGS, settings.audioLangs)
    }
}
