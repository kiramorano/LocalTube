package io.github.kiramorano.localtube.data

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.util.UUID
import java.util.zip.GZIPInputStream
import java.util.zip.GZIPOutputStream

/** Результат импорта: список каналов и количество видеофайлов. */
data class ImportResult(
    val channels: List<String> = emptyList(),
    val imported: Int = 0,
    val error: String? = null
)

/** Результат экспорта канала. */
sealed interface ExportResult {
    /** Успешный экспорт: файл готов к отправке. */
    data class Success(val file: File) : ExportResult

    /** Экспорт с предупреждениями: файл готов, но есть неперекодированные видео. */
    data class PartialSuccess(val file: File, val warnings: List<String>) : ExportResult

    /** Экспорт не удался. */
    data class Error(val message: String) : ExportResult
}

/** Прогресс экспорта: сколько файлов обработано из общего количества видео. */
data class ExportProgress(val done: Int, val total: Int) {
    val fraction: Float get() = if (total > 0) done.toFloat() / total else 0f
}

/**
 * Минимальная реализация tar.gz без сторонних зависимостей.
 *
 * Python использует модуль tarfile; в Android сторонних библиотек нет.
 * Поддерживаются только обычные файлы и каталоги — как filter='data' на ПК:
 * симлинки, устройства и т.п. отбрасываются.
 *
 * Объект не зависит от Context и тестируется в чистой JVM.
 */
object TarUtils {

    private const val BLOCK = 512L
    private const val BLOCK_INT = 512

    /** Упаковывает содержимое [srcDir] в tar.gz с каталогом [channelName] в корне. */
    fun pack(srcDir: File, dest: File, channelName: String) {
        FileOutputStream(dest).use { fos ->
            val gz = GZIPOutputStream(BufferedOutputStream(fos, 8192))
            try {
                // Записываем корневой каталог канала.
                writeHeader(gz, "$channelName/", 0L, isDir = true)
                // Рекурсивно все файлы и подкаталоги.
                srcDir.walkTopDown().forEach { f ->
                    if (f == srcDir) return@forEach
                    val rel = f.toRelativeString(srcDir).replace('\\', '/')
                    val entry = "$channelName/$rel"
                    if (f.isDirectory) {
                        writeHeader(gz, "$entry/", 0L, isDir = true)
                    } else {
                        f.inputStream().use { input ->
                            writeHeader(gz, entry, f.length(), isDir = false)
                            val buf = ByteArray(8192)
                            var total = 0L
                            while (true) {
                                val read = input.read(buf)
                                if (read < 0) break
                                gz.write(buf, 0, read)
                                total += read
                            }
                            writePadding(gz, total)
                        }
                    }
                }
                // Два нулевых блока — маркер конца архива.
                gz.write(ByteArray(BLOCK_INT * 2))
            } finally {
                gz.finish()
                gz.close()
            }
        }
    }

    /**
     * Извлекает tar.gz в [destDir] с проверкой path traversal.
     *
     * Защита зеркалирует Python filter='data': отбрасываем абсолютные пути,
     * компоненты «..» и типы отличные от обычных файлов/каталогов.
     */
    @Throws(IOException::class)
    fun unpack(archive: File, destDir: File) {
        destDir.mkdirs()
        val canonDest = destDir.canonicalPath
        GZIPInputStream(BufferedInputStream(archive.inputStream())).use { gz ->
            val buf = ByteArray(BLOCK_INT)
            while (true) {
                val n = readExact(gz, buf)
                if (n < BLOCK_INT || buf.all { it == 0.toByte() }) break

                val name = readField(buf, 0, 100)
                val prefix = readField(buf, 345, 155)
                val fullName = if (prefix.isNotEmpty()) "$prefix/$name" else name
                if (fullName.isEmpty()) continue

                val size = readOctal(buf, 124, 12)
                val typeflag = buf[156]

                // Отбрасываем симлинки, устройства и т.п. (как filter='data').
                if (typeflag != 0.toByte() && typeflag != '0'.code.toByte() && typeflag != '5'.code.toByte()) {
                    skipBytes(gz, size)
                    skipPadding(gz, size)
                    continue
                }

                // Path traversal: абсолютные пути и «..».
                if (fullName.startsWith("/") || fullName.contains("/..") || fullName.contains("../")) {
                    skipBytes(gz, size)
                    skipPadding(gz, size)
                    continue
                }

                val parts = fullName.split('/').filter { it.isNotEmpty() && it != "." }
                val target = parts.fold(destDir) { acc, part -> File(acc, part) }

                // Финальная проверка: путь не должен выходить за пределы destDir.
                val canonTarget = runCatching { target.canonicalPath }.getOrNull()
                if (canonTarget == null) { skipBytes(gz, size); skipPadding(gz, size); continue }
                if (canonTarget != canonDest && !canonTarget.startsWith(canonDest + File.separator)) {
                    skipBytes(gz, size)
                    skipPadding(gz, size)
                    continue
                }

                if (typeflag == '5'.code.toByte()) {
                    target.mkdirs()
                } else {
                    target.parentFile?.mkdirs()
                    target.outputStream().use { out ->
                        copyBytes(gz, out, size)
                    }
                }
                skipPadding(gz, size)
            }
        }
    }

    /** Записывает 512-байтовый tar-заголовок. */
    private fun writeHeader(out: OutputStream, name: String, size: Long, isDir: Boolean) {
        val header = ByteArray(BLOCK_INT) { 0 }

        // name (0-99)
        writeField(header, 0, 100, name)
        // mode (100-107)
        writeOctal(header, 100, 8, if (isDir) 493L else 420L) // 0755 / 0644 in decimal
        // uid (108-115)
        writeOctal(header, 108, 8, 0L)
        // gid (116-123)
        writeOctal(header, 116, 8, 0L)
        // размер (124-135): 11 цифр + NUL
        writeOctal(header, 124, 12, size)
        // mtime (136-147)
        writeOctal(header, 136, 12, System.currentTimeMillis() / 1000)
        // typeflag (156)
        header[156] = if (isDir) '5'.code.toByte() else '0'.code.toByte()
        // magic (257-262): "ustar\0"
        writeField(header, 257, 6, "ustar\u0000")
        // version (263-264): "00"
        writeField(header, 263, 2, "00")

        // checksum: сумма всех байт, поле chksum считается как 8 пробелов.
        var chksum = 0L
        for (i in header.indices) {
            chksum += if (i in 148..155) 32L else (header[i].toInt() and 0xFF).toLong()
        }
        // Формат: 6 восьмеричных цифр + NUL + пробел.
        val chkStr = chksum.toString(8).padStart(6, '0').take(6) + "\u0000 "
        writeField(header, 148, 8, chkStr)

        out.write(header)
    }

    /** Дописывает нулевой паддинг до границы 512 байт. */
    private fun writePadding(out: OutputStream, dataSize: Long) {
        val padding = (BLOCK - (dataSize % BLOCK)).toInt() % BLOCK_INT
        if (padding > 0) out.write(ByteArray(padding))
    }

    /** Пропускает паддинг в потоке чтения. */
    private fun skipPadding(input: InputStream, dataSize: Long) {
        val padding = (BLOCK - (dataSize % BLOCK)).toInt() % BLOCK_INT
        if (padding > 0) skipBytes(input, padding.toLong())
    }

    private fun readExact(input: InputStream, buf: ByteArray): Int {
        var off = 0
        while (off < buf.size) {
            val read = input.read(buf, off, buf.size - off)
            if (read < 0) return off
            off += read
        }
        return off
    }

    private fun copyBytes(input: InputStream, out: OutputStream, size: Long) {
        var remaining = size
        val buf = ByteArray(8192)
        while (remaining > 0) {
            val toRead = minOf(remaining, buf.size.toLong()).toInt()
            val read = input.read(buf, 0, toRead)
            if (read < 0) break
            out.write(buf, 0, read)
            remaining -= read
        }
    }

    private fun skipBytes(input: InputStream, size: Long) {
        var remaining = size
        val buf = ByteArray(8192)
        while (remaining > 0) {
            val toRead = minOf(remaining, buf.size.toLong()).toInt()
            val read = input.read(buf, 0, toRead)
            if (read < 0) break
            remaining -= read
        }
    }

    private fun writeField(header: ByteArray, offset: Int, length: Int, value: String) {
        val bytes = value.toByteArray(Charsets.UTF_8)
        val len = minOf(bytes.size, length)
        System.arraycopy(bytes, 0, header, offset, len)
    }

    private fun writeOctal(header: ByteArray, offset: Int, length: Int, value: Long) {
        val str = if (value == 0L) "0" else value.toString(8)
        val padded = str.padStart(length - 1, '0') + "\u0000"
        val bytes = padded.toByteArray(Charsets.UTF_8)
        val len = minOf(bytes.size, length)
        System.arraycopy(bytes, 0, header, offset, len)
    }

    private fun readField(buf: ByteArray, offset: Int, length: Int): String {
        var end = offset + length
        while (end > offset && buf[end - 1] == 0.toByte()) end--
        return String(buf, offset, end - offset, Charsets.UTF_8)
    }

    private fun readOctal(buf: ByteArray, offset: Int, length: Int): Long {
        val str = readField(buf, offset, length)
        if (str.isBlank()) return 0L
        return str.trim().toLong(8)
    }

    /** Расширения, которые считаются видео/аудио для подсчёта на импорт. */
    val mediaExts: Set<String> = setOf("mp4", "webm", "mkv", "avi", "mov", "mp3", "m4a", "opus", "aac")
}

/** Экспорт и импорт каналов в формате tar.gz, совместимый с серверной версией. */
class ChannelExportImport(
    private val ctx: Context,
    private val library: Library
) {

    /**
     * Экспорт канала как tar.gz. Аналог /api/channel/<author>/export.
     *
     * При [reencode] видео копируются во временную директорию и перекодируются
     * через ffmpeg (CRF 23, libx264, preset slow, aac 128k) — чтобы архив был
     * совместим с любым устройством. Без перекодировки копируются оригиналы.
     *
     * [onProgress] вызывается после каждого перекодированного файла.
     *
     * Возвращает [ExportResult] с файлом архива или сообщением об ошибке.
     */
    suspend fun exportChannel(
        author: String,
        reencode: Boolean,
        onProgress: ((ExportProgress) -> Unit)? = null
    ): ExportResult = withContext(Dispatchers.IO) {
        val safe = library.safeName(author)
        val srcDir = File(library.root, safe)
        if (!srcDir.isDirectory) {
            return@withContext ExportResult.Error("Канал «$author» не найден в библиотеке")
        }

        val workDir = File(library.tmpRoot, "${safe}_export_${UUID.randomUUID()}").apply { mkdirs() }
        try {
            // Копируем канал во временную директорию.
            val tmpChannel = File(workDir, safe)
            srcDir.copyRecursively(tmpChannel, overwrite = true)

            val errors = mutableListOf<String>()

            // Перекодируем видео, если требуется и ffmpeg доступен.
            if (reencode && Ffmpeg.isAvailable(ctx)) {
                val reencodeExts = setOf("mp4", "webm")
                val mediaFiles = tmpChannel.walkTopDown()
                    .filter { it.isFile && it.extension.lowercase() in reencodeExts }
                    .toList()
                for ((i, f) in mediaFiles.withIndex()) {
                    val tmpOut = File(f.parentFile, f.name + ".tmp.mp4")
                    val result = Ffmpeg.reEncodeForExport(ctx, f, tmpOut)
                    if (result.success && tmpOut.isFile && tmpOut.length() > 0) {
                        // .webm перекодируется в .mp4: переименовываем, чтобы
                        // расширение соответствовало формату контейнера (как на
                        // сервере в app.py api_channel_export).
                        if (f.extension.lowercase() == "webm") {
                            f.delete()
                            tmpOut.renameTo(File(f.parentFile, f.nameWithoutExtension + ".mp4"))
                        } else {
                            replaceFile(tmpOut, f)
                        }
                    } else {
                        tmpOut.delete()
                        // Оригинал остаётся: лучше отдать сырой файл, чем пропустить видео.
                        // Ошибка запоминается, чтобы показать пользователю.
                        errors.add("Не удалось перекодировать: ${f.name} (${result.message})")
                    }
                    onProgress?.invoke(ExportProgress(i + 1, mediaFiles.size))
                }
            }

            // Упаковываем во tar.gz в кэш (доступен через FileProvider для шаринга).
            val finalArchive = File(ctx.cacheDir, "$safe.tar.gz")
            TarUtils.pack(tmpChannel, finalArchive, safe)

            if (errors.isNotEmpty()) {
                ExportResult.PartialSuccess(finalArchive, errors)
            } else {
                ExportResult.Success(finalArchive)
            }
        } catch (e: Exception) {
            ExportResult.Error("Ошибка экспорта: ${e.message ?: "неизвестно"}")
        } finally {
            workDir.deleteRecursively()
        }
    }

    /**
     * Импорт канала из tar.gz. Аналог /api/channel/import.
     *
     * Извлекает архив во временную директорию, для каждого канала:
     * очищает meta-файл, удаляет старую папку, копирует новую,
     * патчит info.json (is_short=false, title), считает видео.
     *
     * Возвращает результат с списком каналов и количеством файлов.
     */
    suspend fun importChannel(archive: File): ImportResult = withContext(Dispatchers.IO) {
        val tmpDir = File(library.tmpRoot, "_import_${UUID.randomUUID()}").apply { mkdirs() }
        try {
            if (!archive.isFile || !archive.name.endsWith(".tar.gz", ignoreCase = true)) {
                return@withContext ImportResult(error = "Файл не является tar.gz архивом")
            }

            try {
                TarUtils.unpack(archive, tmpDir)
            } catch (e: IOException) {
                return@withContext ImportResult(error = "Файл не является корректным tar.gz архивом")
            }

            val extractedDirs = tmpDir.listFiles()?.filter { it.isDirectory } ?: emptyList()
            if (extractedDirs.isEmpty()) {
                return@withContext ImportResult(error = "В архиве нет директории канала")
            }

            val channels = mutableListOf<String>()
            var imported = 0

            for (chDir in extractedDirs) {
                val safe = library.safeName(chDir.name)
                // Очищаем старый meta-файл канала.
                library.clearChannelMeta(safe)

                val dst = File(library.root, safe)
                if (dst.exists()) dst.deleteRecursively()
                chDir.copyRecursively(dst, overwrite = true)

                // Патчим info.json: is_short=false + title fallback.
                dst.walkTopDown().forEach { f ->
                    if (f.isFile && f.name == "info.json") {
                        patchInfoJson(f)
                    }
                }

                // Считаем медиафайлы.
                dst.walkTopDown().forEach { f ->
                    if (f.isFile && f.extension.lowercase() in TarUtils.mediaExts) imported++
                }

                channels.add(safe)
            }

            library.invalidate()
            ImportResult(channels = channels, imported = imported)
        } finally {
            tmpDir.deleteRecursively()
        }
    }

    /** Патчит info.json: гарантирует is_short=false и title. */
    private fun patchInfoJson(file: File) {
        val json = JsonStore.read(file) ?: return
        json.put("is_short", false)
        if (json.optString("title", "").isBlank()) {
            json.put("title", "Видео ${file.parentFile?.name ?: file.nameWithoutExtension}")
        }
        JsonStore.write(file, json)
    }

    /** Заменяет dst файлом tmp атомарно (rename или copy+delete). */
    private fun replaceFile(tmp: File, dst: File) {
        if (!tmp.renameTo(dst)) {
            tmp.copyTo(dst, overwrite = true)
            tmp.delete()
        }
    }
}
