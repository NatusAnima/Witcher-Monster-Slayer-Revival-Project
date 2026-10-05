package io.github.natusanima.slayerrevival

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
