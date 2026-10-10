package io.github.kiramorano.localtube.data

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * Запуск ffmpeg, который поставляется вместе с youtubedl-android.
 *
 * Библиотека умеет только распаковать ffmpeg (FFmpeg.init) и передать путь
 * yt-dlp; публичного API для собственных команд у неё нет. Поэтому бинарник
 * вызывается напрямую из nativeLibraryDir, а окружение собирается так же, как
 * это делает YoutubeDL.init: без LD_LIBRARY_PATH на распакованные
 * packages/ffmpeg/usr/lib процесс падает с ошибкой загрузки libavcodec, а без
 * packages/python/usr/lib — с ошибкой загрузки libc++_shared.so.
 */
object Ffmpeg {

    /** Пресеты конвертации: те же, что CONVERSION_QUALITIES в custom_quality.py. */
    enum class Preset(
        val id: String,
        val label: String,
        val description: String
    ) {
        Q2160("2160", "4K 2160p", "Апскейл до 3840×2160"),
        Q1440("1440", "2K 1440p", "Апскейл до 2560×1440"),
        Q1080("1080", "Full HD 1080p", "1920×1080"),
        Q720("720", "HD 720p", "1280×720"),
        Q480("480", "SD 480p", "854×480"),
        // 360p и 240p добавлены вслед за веб-версией (QUALITY_LABELS): на
        // мобильном интернете 480p всё ещё тяжеловат.
        Q360("360", "360p", "640×360"),
        Q240("240", "240p", "426×240"),
        Q144("144", "Шакализатор 144p", "256×144, битрейт 100k, моно 22 кГц"),
        ENHANCE("enhance", "Улучшайзер", "Резкость и шумоподавление без смены размера"),
        ENHANCE_2160("enhance_2160", "Улучшайзер 4K", "Апскейл до 2160p с резкостью");

        companion object {
            fun from(id: String?): Preset? = entries.firstOrNull { it.id == id }
        }
    }

    /**
     * Аргументы ffmpeg для пресета. Фильтры повторяют серверные: одинаковый
     * результат на ПК и на телефоне.
     */
    private fun presetArgs(preset: Preset): List<String> = when (preset) {
        Preset.Q2160 -> scaleArgs(3840, 2160, crf = 20)
        Preset.Q1440 -> scaleArgs(2560, 1440, crf = 20)
        Preset.Q1080 -> scaleArgs(1920, 1080, crf = 21)
        Preset.Q720 -> scaleArgs(1280, 720, crf = 23)
        Preset.Q480 -> scaleArgs(854, 480, crf = 25)
        Preset.Q360 -> scaleArgs(640, 360, crf = 26)
        Preset.Q240 -> scaleArgs(426, 240, crf = 28)
        // «Шакализатор»: намеренно грубое масштабирование соседним пикселем.
        Preset.Q144 -> listOf(
            "-vf", "scale=256:144:flags=neighbor",
            "-b:v", "100k",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-ac", "1",
            "-ar", "22050",
            "-b:a", "32k",
            "-c:a", "aac"
        )
        Preset.ENHANCE -> listOf(
            "-vf", "unsharp=5:5:1.0:5:5:0.0,eq=contrast=1.05:saturation=1.1,hqdn3d=1.5:1.5:6:6",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "16",
            "-c:a", "copy"
        )
        Preset.ENHANCE_2160 -> listOf(
            "-vf",
            "scale=3840:2160:flags=lanczos,unsharp=5:5:1.0:5:5:0.0," +
                "eq=contrast=1.05:saturation=1.1,hqdn3d=1.5:1.5:6:6",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-c:a", "copy"
        )
    }

    /**
     * Масштабирование с сохранением пропорций. force_original_aspect_ratio с
     * добивкой чёрным: без неё вертикальное видео растягивалось по горизонтали.
     */
    private fun scaleArgs(width: Int, height: Int, crf: Int): List<String> = listOf(
        "-vf",
        "scale=$width:$height:force_original_aspect_ratio=decrease:flags=lanczos," +
            "pad=$width:$height:(ow-iw)/2:(oh-ih)/2:color=black",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", crf.toString(),
        "-c:a", "aac",
        "-b:a", "128k"
    )

    /** Исполняемый ffmpeg лежит рядом с остальными нативными библиотеками. */
    private fun binary(ctx: Context): File =
        File(ctx.applicationInfo.nativeLibraryDir, "libffmpeg.so")

    fun isAvailable(ctx: Context): Boolean = binary(ctx).canExecute()

    /**
     * Окружение как в YoutubeDL.init. Пути указывают на распакованный ffmpeg в
     * noBackupFilesDir, а не в nativeLibraryDir: сами .so лежат внутри
     * libffmpeg.zip.so и распаковываются при инициализации.
     *
     * Кроме папки ffmpeg нужна и папка python: libc++_shared.so лежит только
     * там, а он требуется librubberband.so из состава ffmpeg. Без второго пути
     * линкер не запускает ffmpeg вообще («CANNOT LINK EXECUTABLE»), поэтому
     * молча не работали пресеты качества, извлечение MP3 и создание превью.
     */
    internal fun libraryPath(ctx: Context): String =
        joinLibraryPath(
            File(File(ctx.noBackupFilesDir, "youtubedl-android"), "packages").absolutePath
        )

    /**
     * Собирает LD_LIBRARY_PATH из папки пакетов. Разделитель задан двоеточием
     * явно: File.pathSeparator на машине разработчика под Windows даёт «;»,
     * который Android не понимает.
     */
    internal fun joinLibraryPath(packagesDir: String): String {
        val ffmpegLib = listOf(packagesDir, "ffmpeg", "usr", "lib").joinToString("/")
        val pythonLib = listOf(packagesDir, "python", "usr", "lib").joinToString("/")
        return "$ffmpegLib:$pythonLib"
    }

    private fun environment(ctx: Context): Map<String, String> = mapOf(
        "LD_LIBRARY_PATH" to libraryPath(ctx),
        "HOME" to ctx.cacheDir.absolutePath,
        "TMPDIR" to ctx.cacheDir.absolutePath
    )

    /** Строка "time=00:01:23.45" из вывода ffmpeg в миллисекунды. */
    internal fun parseProgressMs(line: String): Long? {
        val m = Regex("""time=(\d+):(\d\d):(\d\d)[.,](\d+)""").find(line) ?: return null
        val (h, min, s, frac) = m.destructured
        val hours = h.toLongOrNull() ?: return null
        val minutes = min.toLongOrNull() ?: return null
        val seconds = s.toLongOrNull() ?: return null
        // ffmpeg печатает сотые доли, но подстраховываемся от иной точности.
        val fraction = frac.padEnd(3, '0').take(3).toLongOrNull() ?: 0
        return ((hours * 3600 + minutes * 60 + seconds) * 1000) + fraction
    }

    /** Длительность "Duration: 00:04:11.52" из вывода ffmpeg. */
    internal fun parseDurationMs(line: String): Long? {
        val m = Regex("""Duration:\s*(\d+):(\d\d):(\d\d)[.,](\d+)""").find(line) ?: return null
        val (h, min, s, frac) = m.destructured
        val hours = h.toLongOrNull() ?: return null
        val minutes = min.toLongOrNull() ?: return null
        val seconds = s.toLongOrNull() ?: return null
        val fraction = frac.padEnd(3, '0').take(3).toLongOrNull() ?: 0
        return ((hours * 3600 + minutes * 60 + seconds) * 1000) + fraction
    }

    data class Result(val success: Boolean, val message: String)

    /**
     * Запускает ffmpeg и сообщает прогресс долей от 0 до 1.
     *
     * Прогресс считается по времени: общая длительность берётся из строки
     * Duration, которую ffmpeg печатает в самом начале, поэтому знать её заранее
     * не нужно.
     */
    private suspend fun run(
        ctx: Context,
        args: List<String>,
        knownDurationMs: Long = 0,
        onProgress: (Float) -> Unit = {}
    ): Result = withContext(Dispatchers.IO) {
        val bin = binary(ctx)
        if (!bin.canExecute()) {
            return@withContext Result(false, "ffmpeg недоступен: перезапустите приложение")
        }
        val builder = ProcessBuilder(listOf(bin.absolutePath) + args)
        builder.environment().putAll(environment(ctx))
        // ffmpeg пишет прогресс в stderr; сливаем потоки, чтобы читать один.
        builder.redirectErrorStream(true)

        var process: Process? = null
        try {
            process = builder.start()
            var total = knownDurationMs
            // Последние строки нужны для сообщения об ошибке: полный лог ffmpeg
            // огромен, а причина всегда в конце.
            val tail = ArrayDeque<String>()
            process.inputStream.bufferedReader().use { reader ->
                while (true) {
                    val line = reader.readLine() ?: break
                    if (total <= 0) parseDurationMs(line)?.let { total = it }
                    if (total > 0) {
                        parseProgressMs(line)?.let { done ->
                            onProgress((done.toFloat() / total).coerceIn(0f, 1f))
                        }
                    }
                    if (tail.size >= 12) tail.removeFirst()
                    tail.addLast(line)
                }
            }
            val finished = process.waitFor(PROCESS_TIMEOUT_MIN, TimeUnit.MINUTES)
            if (!finished) {
                process.destroyForcibly()
                return@withContext Result(false, "Превышено время обработки")
            }
            if (process.exitValue() == 0) {
                onProgress(1f)
                Result(true, "Готово")
            } else {
                val reason = tail.lastOrNull { it.isNotBlank() }?.take(200) ?: "код ${process.exitValue()}"
                Result(false, "ffmpeg: $reason")
            }
        } catch (e: InterruptedException) {
            // Отмена задачи: процесс нужно убить, иначе он живёт до конца.
            process?.destroyForcibly()
            throw e
        } catch (e: Exception) {
            process?.destroyForcibly()
            Result(false, "ffmpeg: ${(e.message ?: "ошибка").take(200)}")
        }
    }

    /**
     * Конвертирует видео в выбранное качество рядом с исходником:
     * video_1080.mp4 и подобные, как на сервере.
     *
     * Готовый файл ставится на место через rename: при записи прямо в целевой
     * путь прерванная конвертация оставила бы обрезанный файл, который
     * библиотека считает готовым качеством.
     */
    suspend fun convert(
        ctx: Context,
        source: File,
        preset: Preset,
        durationMs: Long = 0,
        onProgress: (Float) -> Unit = {}
    ): Result {
        if (!source.isFile) return Result(false, "Исходный файл не найден")
        val folder = source.parentFile ?: return Result(false, "Нет папки видео")
        val dest = File(folder, "video_${preset.id}.mp4")
        val tmp = File(folder, "video_${preset.id}.tmp.mp4")
        runCatching { tmp.delete() }
        val args = buildList {
            add("-y")
            add("-i"); add(source.absolutePath)
            addAll(presetArgs(preset))
            add("-movflags"); add("+faststart")
            add(tmp.absolutePath)
        }
        val result = run(ctx, args, durationMs, onProgress)
        if (!result.success) {
            runCatching { tmp.delete() }
            return result
        }
        if (tmp.length() <= 0) {
            runCatching { tmp.delete() }
            return Result(false, "ffmpeg вернул пустой файл")
        }
        val moved = tmp.renameTo(dest) || runCatching {
            tmp.copyTo(dest, overwrite = true); tmp.delete(); true
        }.getOrDefault(false)
        return if (moved) Result(true, "Готово: ${preset.label}")
        else Result(false, "Не удалось сохранить результат")
    }

    /**
     * Извлекает звук в MP3 рядом с видео (audio.mp3), как /api/audio/download
     * на сервере. Готовый файл переиспользуется, повторное извлечение не идёт.
     */
    suspend fun extractAudio(
        ctx: Context,
        source: File,
        durationMs: Long = 0,
        onProgress: (Float) -> Unit = {}
    ): Pair<File?, Result> {
        if (!source.isFile) return null to Result(false, "Исходный файл не найден")
        val folder = source.parentFile ?: return null to Result(false, "Нет папки видео")
        val dest = File(folder, "audio.mp3")
        if (dest.isFile && dest.length() > 0) return dest to Result(true, "Файл уже готов")
        val tmp = File(folder, "audio.tmp.mp3")
        runCatching { tmp.delete() }
        val result = run(
            ctx,
            listOf(
                "-y",
                "-i", source.absolutePath,
                // Видеодорожку отбрасываем: без -vn ffmpeg пытается уложить её в mp3.
                "-vn",
                "-c:a", "libmp3lame",
                "-q:a", "2",
                tmp.absolutePath
            ),
            durationMs,
            onProgress
        )
        if (!result.success || tmp.length() <= 0) {
            runCatching { tmp.delete() }
            return null to if (result.success) Result(false, "ffmpeg вернул пустой файл") else result
        }
        val moved = tmp.renameTo(dest) || runCatching {
            tmp.copyTo(dest, overwrite = true); tmp.delete(); true
        }.getOrDefault(false)
        return if (moved) dest to Result(true, "MP3 готов")
        else null to Result(false, "Не удалось сохранить MP3")
    }

    /**
     * Кадр из видео как превью. Аналог download_thumbnails.py: нужен для своих
     * видео и для скачанных без картинки.
     */
    suspend fun extractThumbnail(ctx: Context, source: File, dest: File): Boolean {
        if (!source.isFile) return false
        val tmp = File(dest.parentFile, dest.name + ".tmp.jpg")
        val result = run(
            ctx,
            listOf(
                "-y",
                // Позиция до -i: так ffmpeg перескакивает сразу, а не декодирует
                // всё от начала до третьей секунды.
                "-ss", "3",
                "-i", source.absolutePath,
                "-frames:v", "1",
                "-q:v", "3",
                tmp.absolutePath
            )
        )
        if (!result.success || tmp.length() <= 0) {
            runCatching { tmp.delete() }
            return false
        }
        return tmp.renameTo(dest) || runCatching {
            tmp.copyTo(dest, overwrite = true); tmp.delete(); true
        }.getOrDefault(false)
    }

    /**
     * Перекодирует видео для экспорта канала. Те же параметры, что и на сервере
     * (app.py api_channel_export): CRF 23, libx264, preset slow, aac 128k.
     * Используется при экспорте с галочкой «перекодировать» для переноса между
     * устройствами в совместимые форматы.
     */
    suspend fun reEncodeForExport(ctx: Context, source: File, dest: File): Result {
        if (!source.isFile) return Result(false, "Исходный файл не найден")
        runCatching { dest.delete() }
        val args = listOf(
            "-y",
            "-i", source.absolutePath,
            "-c:v", "libx264",
            "-crf", "23",
            "-preset", "slow",
            "-c:a", "aac",
            "-b:a", "128k",
            dest.absolutePath
        )
        return run(ctx, args)
    }

    /** Верхняя граница на одну операцию: битый файл не должен висеть вечно. */
    private const val PROCESS_TIMEOUT_MIN = 90L
}
