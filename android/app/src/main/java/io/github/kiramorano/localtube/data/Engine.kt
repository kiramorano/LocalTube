package io.github.kiramorano.localtube.data

import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import com.yausername.youtubedl_android.mapper.VideoInfo
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

object Engine {

    suspend fun fetchFormats(url: String): List<FormatOption> = withContext(Dispatchers.IO) {
        val info = YoutubeDL.getInstance().getInfo(url)
        infoToFormats(info)
    }

    suspend fun fetchInfo(url: String): VideoInfo = withContext(Dispatchers.IO) {
        YoutubeDL.getInstance().getInfo(url)
    }

    fun infoToFormats(info: VideoInfo): List<FormatOption> {
        val out = mutableListOf<FormatOption>()
        out += FormatOption(
            formatId = "best",
            label = "Лучшее качество (mp4)",
            isVideo = true,
            resolution = "auto",
            ext = "mp4",
            sizeMb = 0.0,
            fps = 0,
            codec = ""
        )
        val seen = HashSet<Int>()
        for (f in info.formats ?: emptyList()) {
            val h = f.height
            if (h > 0 && f.acodec != "none" && f.vcodec != "none" && seen.add(h)) {
                val size = if (f.fileSize > 0) f.fileSize else f.fileSizeApproximate
                out += FormatOption(
                    formatId = f.formatId ?: "",
                    label = "${h}p${if (f.fps > 30) " ${f.fps}fps" else ""}",
                    isVideo = true,
                    resolution = "${h}p",
                    ext = f.ext ?: "",
                    sizeMb = size / 1024.0 / 1024.0,
                    fps = f.fps,
                    codec = (f.vcodec ?: "").substringBefore(".")
                )
            }
        }
        val seenAudio = HashSet<String>()
        for (f in info.formats ?: emptyList()) {
            val isAudio = (f.vcodec == "none" || f.vcodec.isNullOrBlank()) && !f.acodec.isNullOrBlank()
            if (isAudio) {
                val key = (f.ext ?: "") + (f.abr ?: 0)
                if (!seenAudio.add(key)) continue
                val size = if (f.fileSize > 0) f.fileSize else f.fileSizeApproximate
                out += FormatOption(
                    formatId = f.formatId ?: "",
                    label = "Аудио ${(f.formatNote ?: f.ext ?: "m4a")}",
                    isVideo = false,
                    resolution = "audio",
                    ext = f.ext ?: "m4a",
                    sizeMb = size / 1024.0 / 1024.0,
                    fps = 0,
                    codec = (f.acodec ?: "").substringBefore(".")
                )
            }
        }
        return out
    }

    fun buildRequest(
        url: String,
        formatId: String,
        outDir: File,
        downloadSubs: Boolean,
        subLangs: String
    ): YoutubeDLRequest {
        val req = YoutubeDLRequest(url)
        val f = when {
            formatId == "best" -> "best[ext=mp4]/best"
            formatId.startsWith("video:") -> "${formatId.removePrefix("video:")}+bestaudio"
            formatId.startsWith("audio:") -> formatId.removePrefix("audio:")
            else -> formatId
        }
        req.addOption("-f", f)
        req.addOption("-o", File(outDir, "%(id)s.%(ext)s").absolutePath)
        req.addOption("--merge-output-format", "mp4")
        req.addOption("--write-info-json")
        req.addOption("--write-thumbnail")
        req.addOption("-c")
        req.addOption("--no-mtime")
        req.addOption("--retries", 10)
        req.addOption("--fragment-retries", 10)
        if (downloadSubs && subLangs.isNotBlank()) {
            req.addOption("--write-subs")
            req.addOption("--write-auto-subs")
            req.addOption("--sub-langs", subLangs)
        }
        return req
    }

    suspend fun download(
        request: YoutubeDLRequest,
        processId: String,
        onProgress: (Float) -> Unit
    ) {
        withContext(Dispatchers.IO) {
            YoutubeDL.getInstance().execute(request, processId) { progress, _, _ ->
                onProgress(progress)
            }
        }
    }

    fun cancel(processId: String) {
        YoutubeDL.getInstance().destroyProcessById(processId)
    }
}
