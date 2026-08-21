package io.github.kiramorano.localtube.data

import org.json.JSONObject
import java.io.File

/**
 * Безопасное чтение и запись JSON.
 *
 * Прямая запись в файл обрезает его сразу: сбой на середине оставляет пустой
 * или битый JSON, а прежние данные уже потеряны. Здесь сначала пишется .tmp,
 * затем он переименовывается на место основного файла, а предыдущая версия
 * сохраняется в .bak и используется, если основной файл не читается.
 */
object JsonStore {

    fun read(file: File): JSONObject? {
        readOrNull(file)?.let { return it }
        // Основной файл повреждён или отсутствует: пробуем резервную копию.
        val backup = File(file.parentFile, file.name + ".bak")
        return readOrNull(backup)
    }

    private fun readOrNull(file: File): JSONObject? {
        if (!file.exists() || file.length() == 0L) return null
        return try {
            // Файл мог быть сохранён с BOM, если его правили в редакторе.
            JSONObject(file.readText().removePrefix("\uFEFF"))
        } catch (e: Exception) {
            null
        }
    }

    fun write(file: File, json: JSONObject): Boolean {
        val parent = file.parentFile
        if (parent != null && !parent.exists() && !parent.mkdirs()) return false

        if (file.exists()) {
            try {
                file.copyTo(File(parent, file.name + ".bak"), overwrite = true)
            } catch (e: Exception) {
                // Отсутствие бэкапа не повод терять новые данные.
            }
        }

        val tmp = File(parent, file.name + ".tmp")
        return try {
            tmp.writeText(json.toString(2))
            if (file.exists() && !file.delete()) {
                tmp.delete()
                return false
            }
            if (!tmp.renameTo(file)) {
                // renameTo может не сработать: копируем и убираем временный файл.
                tmp.copyTo(file, overwrite = true)
                tmp.delete()
            }
            true
        } catch (e: Exception) {
            tmp.delete()
            false
        }
    }
}
