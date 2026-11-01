package io.github.natusanima.slayerrevival

import android.content.Context
import android.net.wifi.WifiManager
import android.os.PowerManager
import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/** Downloads [url] into [file], calling [progress] with the bytes so far and the total (-1 if unknown). */
fun download(url: String, file: File, progress: (Long, Long) -> Unit) {
    val connection = URL(url).openConnection() as HttpURLConnection
    connection.connectTimeout = 15_000
    connection.readTimeout = 60_000
    try {
        if (connection.responseCode != 200) throw IOException("HTTP ${connection.responseCode} from ${connection.url.host}")
        val total = connection.contentLengthLong
        file.parentFile?.mkdirs()
        connection.inputStream.use { input ->
            file.outputStream().use { output ->
                val buffer = ByteArray(1 shl 16)
                var done = 0L
                while (true) {
                    val n = input.read(buffer)
                    if (n < 0) break
                    output.write(buffer, 0, n)
                    done += n
                    progress(done, total)
                }
                if (total >= 0 && done != total) throw IOException("the download was cut short")
            }
        }
    } finally {
        connection.disconnect()
    }
}

/**
 * Downloads [url] into [file] and keeps it only if it has [size] bytes and the SHA-256 [sha256]. What arrived before an
 * interruption waits in file.part and the next call resumes from it (a server that answers with the whole file starts it
 * again). Calls [progress] with the file's bytes so far.
 */
fun downloadChecked(url: String, file: File, size: Long, sha256: String, progress: (Long) -> Unit) {
    val part = File(file.path + ".part")
    if (part.length() < size) {
        val have = part.length()
        val connection = URL(url).openConnection() as HttpURLConnection // follows the mirror's redirect to its file server
        connection.connectTimeout = 15_000
        connection.readTimeout = 60_000
        if (have > 0) connection.setRequestProperty("Range", "bytes=$have-")
        try {
            val code = connection.responseCode
            if (code != 200 && code != 206) throw IOException("HTTP $code from ${connection.url.host}")
            var done = if (code == 206) have else 0L
            file.parentFile?.mkdirs()
            connection.inputStream.use { input ->
                java.io.FileOutputStream(part, code == 206).use { output ->
                    val buffer = ByteArray(1 shl 16)
                    while (true) {
                        val n = input.read(buffer)
                        if (n < 0) break
                        output.write(buffer, 0, n)
                        done += n
                        progress(done)
                    }
                }
            }
        } finally {
            connection.disconnect()
        }
    }
    val got = part.length()
    if (got != size || !PlayPacks.matches(PlayPacks.digest(part), sha256)) {
        part.delete()
        throw IOException("${file.name} arrived damaged ($got of $size bytes, or its checksum differs)")
    }
    if (!part.renameTo(file)) throw IOException("could not move ${file.name} into place")
}

/**
 * Keeps the CPU and Wi-Fi from sleeping through a long job, which slows it or stalls it once the screen is off. Returns what
 * lets them go; the CPU lock lapses by itself after [millis].
 */
@Suppress("DEPRECATION")
fun keepAwake(context: Context, tag: String, millis: Long): () -> Unit {
    try {
        val awake = context.getSystemService(PowerManager::class.java).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "slayerrevival:$tag")
            .apply { acquire(millis) }
        val wifi = try {
            context.applicationContext.getSystemService(WifiManager::class.java)
                .createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "slayerrevival:$tag").apply { acquire() }
        } catch (e: Exception) {
            null
        }
        return { wifi?.release(); awake.release() }
    } catch (e: Exception) {
        EventLog.write(context, tag, "could not hold the wake locks: $e")
        return {}
    }
}
