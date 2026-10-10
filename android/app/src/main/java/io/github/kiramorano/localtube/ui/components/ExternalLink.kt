package io.github.kiramorano.localtube.ui.components

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri

/**
 * Ссылка на поддержку автора. Тот же адрес, что в боковой панели веб-версии
 * (templates/index.html) и в настройках (templates/settings.html): в вебе
 * кнопка есть в двух местах, и в приложении она должна быть в тех же.
 */
const val DONATE_URL = "https://www.donationalerts.com/r/localteam"

/**
 * Открывает внешнюю ссылку в браузере.
 *
 * Возвращает `false`, если открыть нечем. На Android TV браузера часто нет
 * вовсе, и `startActivity` с ACTION_VIEW там валит приложение с
 * ActivityNotFoundException — то есть нажатие на «Поддержать автора» на
 * телевизоре означало бы вылет. Исключение перехватываем, а вызывающий по
 * ответу решает, что показать вместо перехода.
 *
 * FLAG_ACTIVITY_NEW_TASK обязателен: контекст приложения (а не активности) без
 * него бросает исключение, а Compose-код получает именно application context в
 * части конфигураций.
 */
fun openExternalLink(context: Context, url: String): Boolean {
    val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    return try {
        context.startActivity(intent)
        true
    } catch (e: ActivityNotFoundException) {
        false
    }
}
