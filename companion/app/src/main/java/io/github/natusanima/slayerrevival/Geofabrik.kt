package io.github.natusanima.slayerrevival

import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/**
 * Geofabrik's `-latest.osm.pbf` links answer 307 to a dated file that never changes and serves Range requests, so that
 * file is what gets downloaded and resumed: a dropped connection costs the part that is missing, not the whole extract.
 */
object Geofabrik {
    /** The dated file behind a `-latest` link, and its size. */
    class Extract(val url: String, val bytes: Long)

    /** Geofabrik is refusing this network for now (it limits downloads per address): trying again at once only makes it worse. */
    class Limited(message: String) : IOException(message)

    private fun open(url: String, method: String): HttpURLConnection {
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.requestMethod = method
        connection.instanceFollowRedirects = false
        connection.connectTimeout = 15_000
        connection.readTimeout = 60_000
        connection.setRequestProperty("User-Agent", "WitcherMonsterSlayerRevival (+https://github.com/${Updates.REPO})")
        return connection
    }

    private fun refused(code: Int) = when (code) {
        429, 503 -> Limited("Geofabrik is limiting downloads from this network right now (HTTP $code). Try again in a while, or " +
            "switch between Wi-Fi and mobile data.")
        404 -> IOException("Geofabrik no longer has this file (HTTP 404). Pick the region again.")
        else -> IOException("Geofabrik answered HTTP $code")
    }

    /** Follows the redirect from [latest] to the dated file and asks its size. Throws if Geofabrik does not answer 200. */
    fun resolve(latest: String): Extract {
        var url = latest
        repeat(4) {
            val connection = open(url, "HEAD")
            try {
                val code = connection.responseCode
                when {
                    code in 301..308 -> url = URL(URL(url), connection.getHeaderField("Location") ?: throw IOException("a redirect without a place")).toString()
                    code == 200 -> return Extract(url, connection.contentLengthLong)
                    else -> throw refused(code)
                }
            } finally {
                connection.disconnect()
            }
        }
        throw IOException("Geofabrik redirected too many times")
    }

    /**
     * Downloads [url] into [part], carrying on from what is already there. [progress] gets the bytes in the file; [cancelled] is
     * asked between reads. A dropped connection is retried (4 times in a row, a new count whenever bytes arrived), but a refusal
     * from Geofabrik is not. Returns when the file has [total] bytes.
     */
    fun download(url: String, part: File, total: Long, progress: (Long) -> Unit, cancelled: () -> Boolean) {
        var attempt = 1
        while (true) {
            if (cancelled()) throw IOException("cancelled")
            val have = part.length()
            if (total > 0 && have == total) return
            if (total > 0 && have > total) { // not this file's bytes
                part.delete()
                continue
            }
            val connection = open(url, "GET")
            try {
                connection.instanceFollowRedirects = true // the dated file does not redirect, but a mirror might
                connection.setRequestProperty("Accept-Encoding", "identity")
                if (have > 0) connection.setRequestProperty("Range", "bytes=$have-")
                val code = connection.responseCode
                if (code == 416) { // what we have does not fit what is there now: start over
                    part.delete()
                    continue
                }
                if (code != 200 && code != 206) throw refused(code)
                if (code == 200 && have > 0) part.delete() // the whole file again, not the rest of it
                part.parentFile?.mkdirs()
                FileOutputStream(part, code == 206).use { out ->
                    connection.inputStream.use { input ->
                        val buffer = ByteArray(1 shl 16)
                        var done = part.length()
                        while (true) {
                            val n = input.read(buffer)
                            if (n < 0) break
                            if (cancelled()) throw IOException("cancelled")
                            out.write(buffer, 0, n)
                            done += n
                            progress(done)
                        }
                    }
                }
                if (total <= 0 || part.length() == total) return
                throw IOException("the download was cut short")
            } catch (e: IOException) {
                if (part.length() > have) attempt = 1 // bytes arrived: a flaky connection that keeps moving is allowed to carry on
                if (e is Limited || cancelled() || attempt >= 4) throw e
                attempt++
                Thread.sleep(2_000L * attempt)
            } finally {
                connection.disconnect()
            }
        }
    }
}
