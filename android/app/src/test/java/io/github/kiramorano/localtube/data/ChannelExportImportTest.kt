package io.github.kiramorano.localtube.data

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.io.FileOutputStream
import java.nio.charset.StandardCharsets
import java.util.zip.GZIPOutputStream

/**
 * Тесты упаковки/распаковки tar.gz и патчинга info.json.
 *
 * TarUtils не зависит от Context и тестируется в чистой JVM — без Robolectric.
 * Это важно: Robolectric 4.13 несовместим с JDK 26, и 82 теста с ним падают.
 */
class ChannelExportImportTest {

    // --- helpers ----------------------------------------------------------------

    /** Создаёт tar.gz-архив с одной записью [entryName] и содержимым [content]. */
    private fun createTarGz(dest: File, entryName: String, content: ByteArray) {
        val header = ByteArray(512) { 0 }

        // name (0–99)
        val nameBytes = entryName.toByteArray(StandardCharsets.UTF_8)
        System.arraycopy(nameBytes, 0, header, 0, minOf(nameBytes.size, 100))

        // mode (100–107): 0644 → 420
        writeOctal(header, 100, 8, 420L)

        // size (124–135)
        writeOctal(header, 124, 12, content.size.toLong())

        // typeflag (156): '0' = обычный файл
        header[156] = '0'.code.toByte()

        // magic (257–262): "ustar\0"
        val magic = "ustar\u0000".toByteArray(StandardCharsets.UTF_8)
        System.arraycopy(magic, 0, header, 257, minOf(magic.size, 6))

        // version (263–264): "00"
        val version = "00".toByteArray(StandardCharsets.UTF_8)
        System.arraycopy(version, 0, header, 263, minOf(version.size, 2))

        // checksum (148–155): сумма всех байт, поле chksum считается как 8 пробелов
        var chksum = 0L
        for (i in header.indices) {
            chksum += if (i in 148..155) 32L else (header[i].toInt() and 0xFF).toLong()
        }
        val chkStr = chksum.toString(8).padStart(6, '0').take(6) + "\u0000 "
        val chkBytes = chkStr.toByteArray(StandardCharsets.UTF_8)
        System.arraycopy(chkBytes, 0, header, 148, minOf(chkBytes.size, 8))

        FileOutputStream(dest).use { fos ->
            val gz = GZIPOutputStream(fos)
            gz.write(header)
            gz.write(content)
            // паддинг до границы 512 байт
            val padding = (512 - (content.size % 512)) % 512
            if (padding > 0) gz.write(ByteArray(padding))
            // два нулевых блока — конец архива
            gz.write(ByteArray(1024))
            gz.finish()
            gz.close()
        }
    }

    private fun writeOctal(header: ByteArray, offset: Int, length: Int, value: Long) {
        val str = if (value == 0L) "0" else value.toString(8)
        val padded = str.padStart(length - 1, '0') + "\u0000"
        val bytes = padded.toByteArray(StandardCharsets.UTF_8)
        System.arraycopy(bytes, 0, header, offset, minOf(bytes.size, length))
    }

    // --- tests ------------------------------------------------------------------

    @Test
    fun testTarRoundtrip() {
        val srcDir = createTempDir("lt-tar-src")
        val vidDir = File(srcDir, "vid1")
        vidDir.mkdirs()
        File(vidDir, "info.json").writeText("""{"id":"vid1","title":"test","is_short":true}""")
        File(vidDir, "video.mp4").writeText("fake mp4 content")

        val archive = File(createTempDir("lt-tar-arch"), "channel.tar.gz")
        TarUtils.pack(vidDir, archive, "vid1")

        val extractDir = createTempDir("lt-tar-ext")
        TarUtils.unpack(archive, extractDir)

        val extractedVidDir = File(extractDir, "vid1")
        assertTrue(extractedVidDir.isDirectory)
        assertTrue(File(extractedVidDir, "info.json").isFile)
        assertTrue(File(extractedVidDir, "video.mp4").isFile)

        // содержимое файлов должно совпадать
        val info = JSONObject(File(extractedVidDir, "info.json").readText())
        assertEquals("vid1", info.getString("id"))
        assertEquals("test", info.getString("title"))
        assertEquals(true, info.getBoolean("is_short"))

        val mp4 = File(extractedVidDir, "video.mp4")
        assertEquals("fake mp4 content", mp4.readText())

        srcDir.deleteRecursively()
        archive.parentFile?.deleteRecursively()
        extractDir.deleteRecursively()
    }

    @Test
    fun testTarPathTraversal() {
        val destDir = createTempDir("lt-tar-traversal")
        // evil.txt должен оказаться рядом с destDir, а не внутри него.
        val evilFile = File(destDir.parentFile, "evil.txt")
        assertFalse(evilFile.exists())

        val archive = File(createTempDir("lt-tar-malicious"), "bad.tar.gz")
        createTarGz(archive, "../../evil.txt", "pwned".toByteArray())

        TarUtils.unpack(archive, destDir)

        // Файл НЕ должен быть создан за пределами destDir — путь traversal отбракован.
        assertFalse(evilFile.exists())
        // Внутри destDir тоже ничего не должно быть.
        assertEquals(0, destDir.listFiles()?.size ?: -1)

        destDir.deleteRecursively()
        archive.parentFile?.deleteRecursively()
    }

    @Test
    fun testInfoJsonPatch() {
        val dir = createTempDir("lt-patch")
        val infoFile = File(dir, "info.json")
        infoFile.writeText("""{"is_short":true,"title":""}""")

        // Симуляция patchInfoJson из ChannelExportImport: читаем → патчим → пишем.
        val json = JsonStore.read(infoFile)!!
        json.put("is_short", false)
        if (json.optString("title", "").isBlank()) {
            json.put("title", "Видео ${infoFile.parentFile?.name ?: infoFile.nameWithoutExtension}")
        }
        JsonStore.write(infoFile, json)

        val patched = JSONObject(infoFile.readText())
        assertEquals(false, patched.getBoolean("is_short"))
        assertEquals("Видео ${dir.name}", patched.getString("title"))

        dir.deleteRecursively()
    }

    @Test
    fun testMediaExtensionsCoversCommonFormats() {
        assertTrue("mp4" in TarUtils.mediaExts)
        assertTrue("webm" in TarUtils.mediaExts)
        assertTrue("mp3" in TarUtils.mediaExts)
        assertTrue("m4a" in TarUtils.mediaExts)
        assertFalse("txt" in TarUtils.mediaExts)
        assertFalse("json" in TarUtils.mediaExts)
    }
}
