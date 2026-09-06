package io.github.kiramorano.localtube.data

import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream

/**
 * Безопасное чтение и запись JSON.
 *
 * Прямая запись в файл обрезает его сразу: сбой на середине оставляет пустой
 * или битый JSON, а прежние данные уже потеряны. Здесь сначала пишется .tmp,
 * затем он переименовывается на место основного файла, а предыдущая версия
 * сохраняется в .bak и используется, если основной файл не читается.
 */
object JsonStore {

    /**
     * Замок на каждый путь. Без него два потока (например, UI, отменяющий
     * задачу, и воркер, обновляющий прогресс) писали в один и тот же .tmp и
     * переименовывали в основной файл перемешанный мусор.
     */
    private val locks = HashMap<String, Any>()

    private fun lockFor(file: File): Any = synchronized(locks) {
        locks.getOrPut(file.absolutePath) { Any() }
    }

    fun read(file: File): JSONObject? = synchronized(lockFor(file)) {
        readOrNull(file)?.let { return@synchronized it }
        // Основной файл повреждён или отсутствует: пробуем резервную копию.
        readOrNull(File(file.parentFile, file.name + ".bak"))
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

    fun write(file: File, json: JSONObject): Boolean = synchronized(lockFor(file)) {
        val parent = file.parentFile
        if (parent != null && !parent.exists() && !parent.mkdirs()) return@synchronized false

        // Текст готовим до любых операций с файлами: сбой сериализации не
        // должен трогать уже сохранённые данные.
        val text = try {
            json.toString(2)
        } catch (e: Exception) {
            return@synchronized false
        }

        if (file.exists()) {
            try {
                file.copyTo(File(parent, file.name + ".bak"), overwrite = true)
            } catch (e: Exception) {
                // Отсутствие бэкапа не повод терять новые данные.
            }
        }

        val tmp = File(parent, file.name + ".tmp")
        return@synchronized try {
            // fsync перед переименованием: иначе rename попадёт в журнал
            // раньше самих данных и после сбоя питания останется пустой файл.
            FileOutputStream(tmp).use { out ->
                out.write(text.toByteArray(Charsets.UTF_8))
                out.flush()
                out.fd.sync()
            }
            // rename на Android заменяет существующий файл, поэтому удалять
            // его заранее нельзя: в этом окне файла не существует вовсе.
            if (!tmp.renameTo(file)) {
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
