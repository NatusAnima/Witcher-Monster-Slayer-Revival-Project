package io.github.natusanima.slayerrevival

import android.content.Context
import android.os.SystemClock
import android.util.Base64
import com.aurora.gplayapi.data.models.AuthData
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.InputStream
import java.io.SequenceInputStream
import java.math.BigInteger
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.util.Enumeration
import java.util.Locale
import java.util.TimeZone
import java.util.UUID
import java.util.concurrent.Callable
import java.util.concurrent.ExecutionException
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicLong
import java.util.zip.GZIPInputStream
import java.util.zip.GZIPOutputStream
import java.util.zip.ZipException
import java.util.zip.ZipFile

/**
 * Fetches the game's 26 extra asset packs from Google Play the way the Play Store serves them to the game's own
 * Play Core library, so the playable client can be built on this phone with no PC. The request and the headers
 * follow microG's open-source implementation (Apache-2.0); sign-in and device registration are gplayapi's.
 * Every pack is checked against the size and SHA-256 of the original (assets/packs.txt) before it is kept.
 */
object PlayPacks {
    class Pack(val name: String, val size: Long, val sha256: String)
    private class Chunk(val bytes: Long, val sha256: String, val url: String)
    private class Slice(val id: String, val size: Long, val sha256: String, val format: Int, val chunks: List<Chunk>)

    /** A byte range of a chunk, kept in a file of its own so that several can come at once. */
    private class Piece(val file: File, val chunk: Chunk, val start: Long, val length: Long)

    private const val DELIVERY = "https://play-fe.googleapis.com/fdfe/assetModuleDelivery"
    private const val SYNC = "https://play-fe.googleapis.com/fdfe/sync"
    private const val PLAY_CORE = 11000L // what the game's own Play Core library reports
    private const val PIECE = 8L shl 20
    private const val FINSKY = "Finsky/37.5.24-29%20%5B0%5D%20%5BPR%5D%20565477504"
    private const val TARGETS = "CAESN/qigQYC2AMBFfUbyA7SM5Ij/CvfBoIDgxHqGP8R3xzIBvoQtBKFDZ4HAY4FrwSVMasHBO0O2Q8akgYRAQECAQO7AQEpKZ0CnwECAwRrAQYBr9PPAoK7sQMBAQMCBAkIDAgBAwEDBAICBAUZEgMEBAMLAQEBBQEBAcYBARYED+cBfS8CHQEKkAEMMxcBIQoUDwYHIjd3DQ4MFk0JWGYZEREYAQOLAYEBFDMIEYMBAgICAgICOxkCD18LGQKEAcgDBIQBAgGLARkYCy8oBTJlBCUocxQn0QUBDkkGxgNZQq0BZSbeAmIDgAEBOgGtAaMCDAOQAZ4BBIEBKUtQUYYBQscDDxPSARA1oAEHAWmnAsMB2wFyywGLAxol+wImlwOOA80CtwN26A0WjwJVbQEJPAH+BRDeAfkHK/ABASEBCSAaHQemAzkaRiu2Ad8BdXeiAwEBGBUBBN4LEIABK4gB2AFLfwECAdoENq0CkQGMBsIBiQEtiwGgA1zyAUQ4uwS8AwhsvgPyAcEDF27vApsBHaICGhl3GSKxAR8MC6cBAgItmQYG9QIeywLvAeYBDArLAh8HASI4ELICDVmVBgsY/gHWARtcAsMBpALiAdsBA7QBpAJmIArpByn0AyAKBwHTARIHAX8D+AMBcRIBBbEDmwUBMacCHAciNp0BAQF0OgQLJDuSAh54kwFSP0eeAQQ4M5EBQgMEmwFXywFo0gFyWwMcapQBBugBPUW2AVgBKmy3AR6PAbMBGQxrUJECvQR+8gFoWDsYgQNwRSczBRXQAgtRswEW0ALMAREYAUEBIG6yATYCRE8OxgER8gMBvQEDRkwLc8MBTwHZAUOnAXiiBakDIbYBNNcCIUmuArIBSakBrgFHKs0EgwV/G3AD0wE6LgECtQJ4xQFwFbUCjQPkBS6vAQqEAUZF3QIM9wEhCoYCQhXsBCyZArQDugIziALWAdIBlQHwBdUErQE6qQaSA4EEIvYBHir9AQVLmgMCApsCKAwHuwgrENsBAjNYswEVmgIt7QJnN4wDEnta+wGfAcUBxgEtEFXQAQWdAUAeBcwBAQM7rAEJATJ0LENrdh73A6UBhAE+qwEeASxLZUMhDREuH0CGARbd7K0GlQo"
    private const val PHENOTYPE = "H4sIAAAAAAAAAB3OO3KjMAAA0KRNuWXukBkBQkAJ2MhgAZb5u2GCwQZbCH_EJ77QHmgvtDtbv-Z9_H63zXXU0NVPB1odlyGy7751Q3CitlPDvFd8lxhz3tpNmz7P92CFw73zdHU2Ie0Ad2kmR8lxhiErTFLt3RPGfJQHSDy7Clw10bg8kqf2owLokN4SecJTLoSwBnzQSd652_MOf2d1vKBNVedzg4ciPoLz2mQ8efGAgYeLou-l-PXn_7Sna1MfhHuySxt-4esulEDp8Sbq54CPPKjpANW-lkU2IZ0F92LBI-ukCKSptqeq1eXU96LD9nZfhKHdtjSWwJqUm_2r6pMHOxk01saVanmNopjX3YxQafC4iC6T55aRbC8nTI98AF_kItIQAJb5EQxnKTO7TZDWnr01HVPxelb9A2OWX6poidMWl16K54kcu_jhXw-JSBQkVcD_fPsLSZu6joIBAAA"

    /** The 26 packs, smallest first so a refusal from Google shows up before the long downloads. */
    fun expected(context: Context): List<Pack> = context.assets.open("packs.txt").bufferedReader().readLines()
        .filter { it.isNotBlank() }.map { line -> line.split(' ', limit = 3).let { Pack(it[2], it[0].toLong(), it[1]) } }
        .sortedBy { it.size }

    /**
     * Tells Google Play what this phone is, as the Play Store does once a day (microG calls it the device sync).
     * Without it a delivery can come back with no pack data. Built from the profile the phone was registered with.
     */
    fun sync(context: Context, auth: AuthData) {
        val p = auth.deviceInfoProvider!!.properties
        fun text(key: String) = p.getProperty(key).orEmpty()
        fun number(key: String, default: Long = 0) = p.getProperty(key)?.toLongOrNull() ?: default
        fun list(key: String) = text(key).split(',').filter { it.isNotEmpty() }
        val id = BigInteger(auth.gsfId, 16).toLong()
        val account = encode(MessageDigest.getInstance("SHA-256").digest("$id-${auth.email}".toByteArray()))
        val zone = TimeZone.getDefault().rawOffset
        val width = number("Screen.Width")
        val height = number("Screen.Height")
        val density = number("Screen.Density", 420)
        val body = Pb()
            .msg(1) { msg(7) { msg(1) { str(1, account) } } } // this account on this device
            .msg(1) { msg(8) { msg(1) { str(1, account) } } }
            .msg(1) {
                msg(10) { // what the device can do
                    list("Features").forEach { msg(1) { str(1, it).int(2, 0) } }
                    list("SharedLibraries").forEach { str(2, it) }
                    list("Locales").forEach { str(3, it.replace('_', '-')) }
                    list("GL.Extensions").forEach { str(4, it) }
                    int(5, 0)
                }
            }
            .msg(1) { msg(11) { int(1, number("Keyboard")).int(2, 0).int(3, number("Navigation")) } }
            .msg(1) {
                msg(12) {
                    str(1, text("Build.MANUFACTURER")).str(2, text("Build.MODEL")).str(3, text("Build.DEVICE"))
                        .str(4, text("Build.PRODUCT")).str(5, text("Build.BRAND"))
                }
            }
            .msg(1) { msg(13) {} }
            .msg(1) {
                msg(15) {
                    int(1, 0).int(2, number("TotalMemoryBytes", 8589935000L)).int(3, number("MaxNumOfCPUCores", 8))
                    list("Platforms").forEach { str(4, it) }
                }
            }
            .msg(1) { msg(16) { str(1, "GMT%+d:%02d".format(Locale.US, zone / 3_600_000, Math.abs(zone / 60_000 % 60))) } }
            .msg(1) { msg(18) { str(1, "am-google").str(2, "play-ms-android-google").str(3, "play-ad-ms-android-google") } }
            .msg(1) { msg(19) { int(2, number("Vending.version")) } }
            .msg(1) {
                msg(20) {
                    int(1, number("TouchScreen")).int(2, width).int(3, height)
                        .int(4, stablePoint(width.toInt(), height.toInt(), density.toInt()).toLong()).int(5, density)
                }
            }
            .msg(1) {
                msg(21) {
                    str(1, text("Build.FINGERPRINT")).int(2, number("Build.VERSION.SDK_INT")).str(4, "REL").int(6, number("GL.Version"))
                }
            }
            .toBytes()
        val reply = post(SYNC, headers(auth), body)
        PlayLog.write(context, "device sync: HTTP ${reply.code}, ${reply.body.size} bytes")
    }

    /** The Play Store's size class for a screen, as microG works it out. */
    private fun stablePoint(x: Int, y: Int, density: Int): Int {
        val long = (y * (160f / density)).toInt()
        if (long < 470) return 17
        val short = (x * (160f / density)).toInt()
        if (long >= 960 && short >= 720) return if (long * 3 / 5 < short - 1) 20 else 4
        val size = if (long < 640 || short < 480) 2 else 3
        return if (long * 3 / 5 < short - 1) size or 16 else size
    }

    /**
     * Downloads [pack] into [dir] unless it is already there, over [connections] parallel connections (one means a
     * single stream). [progress] gets the bytes of the pack so far, from any thread; it may throw to stop. A failed
     * or interrupted download resumes where it stopped, from the pieces kept in the work folder.
     */
    fun fetch(context: Context, auth: AuthData, pack: Pack, dir: File, connections: Int, progress: (Long) -> Unit) {
        val target = File(dir, pack.name)
        if (target.length() == pack.size) return progress(pack.size)
        dir.mkdirs()
        val slices = deliver(context, auth, pack.name)
        val work = File(context.filesDir, "game/work/${pack.name}").apply { mkdirs() }
        work.listFiles()?.filter { !it.name.startsWith("seg-") }?.forEach { it.delete() } // an old layout, or a half-made join
        val size = if (connections > 1) PIECE else Long.MAX_VALUE
        // slice -> chunk -> the pieces of that chunk
        val plan = slices.mapIndexed { s, slice ->
            slice.chunks.mapIndexed { c, chunk ->
                generateSequence(0L) { it + size }.takeWhile { it < chunk.bytes }.map { start ->
                    Piece(File(work, "seg-$s-$c-${start / size}"), chunk, start, minOf(size, chunk.bytes - start))
                }.toList()
            }
        }
        val pieces = plan.flatten().flatten()
        val total = pieces.sumOf { it.length }.coerceAtLeast(1)
        val received = AtomicLong(pieces.sumOf { p ->
            val have = p.file.length()
            if (have > p.length) { p.file.delete(); 0L } else have
        })
        progress(received.get() * pack.size / total)
        val started = SystemClock.elapsedRealtime()
        val pool = Executors.newFixedThreadPool(connections.coerceAtLeast(1))
        try {
            pieces.map { p -> pool.submit(Callable { retry { download(p, received) { now -> progress(now * pack.size / total) } } }) }
                .forEach { future ->
                    try {
                        future.get()
                    } catch (e: ExecutionException) {
                        throw e.cause ?: e
                    }
                }
        } finally {
            pool.shutdownNow()
        }
        val seconds = (SystemClock.elapsedRealtime() - started).coerceAtLeast(1) / 1000.0
        PlayLog.write(context, "${pack.name}: ${total / 1_000_000} MB in ${"%.1f".format(Locale.US, seconds)} s, " +
            "${"%.1f".format(Locale.US, total / 1_000_000 / seconds)} MB/s over ${connections.coerceAtLeast(1)} connection(s)")
        unpack(context, pack, slices, plan, work, target)
        work.deleteRecursively()
        progress(pack.size)
    }

    private fun deliver(context: Context, auth: AuthData, pack: String): List<Slice> {
        val request = Pb().str(1, MainActivity.GAME).msg(2) { int(1, MainActivity.GAME_VERSION) }.int(3, PLAY_CORE)
            .int(4, 0).int(4, 1) // compression: none, chunked gzip
            .int(5, 1).int(5, 2) // patches: gdiff, gzipped gdiff
            .msg(6) { str(1, pack) }.toBytes()
        val reply = post(DELIVERY, headers(auth), request)
        PlayLog.write(context, "delivery $pack: HTTP ${reply.code}, ${reply.body.size} bytes")
        if (reply.code != 200) {
            val detail = String(reply.body.copyOf(minOf(reply.body.size, 200))).filter { it.isLetterOrDigit() || it in " .,:_-" }
            throw IOException("Google Play answered HTTP ${reply.code}" + if (detail.isEmpty()) "" else ": $detail")
        }
        val info = try {
            read(reply.body).one(1)?.fields()?.one(151)?.fields()
        } catch (e: RuntimeException) {
            PlayLog.write(context, "unreadable delivery answer: ${Base64.encodeToString(reply.body.copyOf(minOf(reply.body.size, 300)), Base64.NO_WRAP)}")
            throw IOException("Google Play's answer wasn't understood")
        }
        val module = info?.takeIf { it.one(4) == null }?.many(3)?.map { it.fields() }?.firstOrNull { it.one(1)?.text() == pack }
        if (module == null) { // there is nothing to download in it, so nothing secret: its shape tells what Google meant
            PlayLog.write(context, "delivery answer for $pack: ${dump(reply.body)}")
            val status = info?.one(4)?.let { " (status ${it.value})" }.orEmpty()
            throw IOException("Google Play returned no data for $pack$status. If this account never had the game, " +
                "Google may not offer it the extra data.")
        }
        return module.many(3).map { slice ->
            val fields = slice.fields()
            val full = fields.one(2)?.fields() ?: throw IOException("Google Play gave no full download for $pack")
            Slice(
                id = fields.one(1)?.fields()?.one(1)?.text().orEmpty(),
                size = full.one(1)?.value ?: 0,
                sha256 = full.one(2)?.text().orEmpty(),
                format = full.one(3)?.value?.toInt() ?: 0,
                chunks = full.many(4).map { c ->
                    val f = c.fields()
                    Chunk(f.one(1)?.value ?: 0, f.one(2)?.text().orEmpty(), f.one(3)?.text().orEmpty())
                },
            )
        }.also { slices ->
            PlayLog.write(context, "$pack: " + slices.joinToString { s ->
                "slice ${s.id} format ${s.format} ${s.size} bytes in ${s.chunks.size} chunk(s)"
            })
        }
    }

    /** Fetches one piece into its file, resuming a partial one. [onBytes] gets the pack's running total of bytes. */
    private fun download(piece: Piece, received: AtomicLong, onBytes: (Long) -> Unit) {
        var have = piece.file.length()
        if (have < piece.length) {
            val whole = piece.start == 0L && piece.length == piece.chunk.bytes
            val connection = URL(piece.chunk.url).openConnection() as HttpURLConnection
            connection.connectTimeout = 20_000
            connection.readTimeout = 60_000
            connection.setRequestProperty("Accept-Encoding", "identity") // the bytes as stored, not re-compressed on the way
            if (!(whole && have == 0L)) {
                connection.setRequestProperty("Range", "bytes=${piece.start + have}-${piece.start + piece.length - 1}")
            }
            try {
                val code = connection.responseCode
                if (code == 200) {
                    if (!whole) throw IOException("the server does not send parts of a download")
                    if (have > 0) { // it sent the whole chunk, not the rest
                        received.addAndGet(-have)
                        have = 0
                    }
                } else if (code != 206) {
                    throw IOException("HTTP $code from ${connection.url.host}")
                }
                FileOutputStream(piece.file, have > 0).use { out ->
                    connection.inputStream.use { input -> // read to the end and closed, so the connection can be reused
                        val buffer = ByteArray(1 shl 18)
                        while (true) {
                            val n = input.read(buffer)
                            if (n < 0) break
                            out.write(buffer, 0, n)
                            onBytes(received.addAndGet(n.toLong()))
                        }
                    }
                }
            } catch (e: IOException) {
                connection.disconnect()
                throw e
            }
        }
        if (piece.file.length() != piece.length) throw IOException("a download was cut short")
    }

    /** Joins a pack's pieces, takes the pack file out of the archive they make, and keeps it only if it is the original. */
    private fun unpack(context: Context, pack: Pack, slices: List<Slice>, plan: List<List<List<Piece>>>, work: File, target: File) {
        val part = File(target.path + ".part").apply { delete() }
        val started = SystemClock.elapsedRealtime()
        try {
            var hash: ByteArray? = null
            for ((s, slice) in slices.withIndex()) {
                val whole = File(work, "slice-$s")
                whole.outputStream().use { sink ->
                    for (pieces in plan[s]) {
                        val source = SequenceInputStream(object : Enumeration<InputStream> {
                            private val files = pieces.iterator()
                            override fun hasMoreElements() = files.hasNext()
                            override fun nextElement(): InputStream = files.next().file.inputStream()
                        })
                        (if (slice.format == 1) GZIPInputStream(source, 1 shl 16) else source).use { it.copyTo(sink, 1 shl 20) }
                    }
                }
                if (slice.size > 0 && whole.length() != slice.size) {
                    throw IOException("${pack.name}: ${whole.length()} bytes after joining, Google Play said ${slice.size}")
                }
                try {
                    ZipFile(whole).use { zip ->
                        val entry = zip.getEntry("assets/assetpack/${pack.name}")
                        if (entry == null) {
                            PlayLog.write(context, "${pack.name}: the archive holds " + zip.entries().asSequence().take(8).joinToString { it.name })
                        } else {
                            val sha = MessageDigest.getInstance("SHA-256") // hashed on the way out: no second read of the pack
                            zip.getInputStream(entry).use { input ->
                                part.outputStream().use { out ->
                                    val buffer = ByteArray(1 shl 20)
                                    while (true) {
                                        val n = input.read(buffer)
                                        if (n < 0) break
                                        sha.update(buffer, 0, n)
                                        out.write(buffer, 0, n)
                                    }
                                }
                            }
                            hash = sha.digest()
                        }
                    }
                } catch (e: ZipException) {
                    PlayLog.write(context, "${pack.name}: the slice is not an archive (${e.message}); using it as the pack itself")
                    if (!whole.renameTo(part)) throw IOException("could not move the pack into place")
                }
                if (part.exists()) break
            }
            if (!part.exists()) throw IOException("${pack.name}: no pack file inside what Google Play sent")
            if (part.length() != pack.size || !matches(hash ?: digest(part), pack.sha256)) {
                throw IOException("${pack.name} is not the original (${part.length()} of ${pack.size} bytes, or its checksum differs)")
            }
            if (!part.renameTo(target)) throw IOException("could not move ${pack.name} into place")
            PlayLog.write(context, "${pack.name}: verified, ${pack.size} bytes, unpacked in ${(SystemClock.elapsedRealtime() - started) / 1000} s")
        } catch (e: IOException) {
            part.delete()
            work.deleteRecursively() // what was downloaded is suspect: start this pack afresh next time
            throw e
        }
    }

    private fun digest(file: File): ByteArray {
        val sha = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(1 shl 20)
            while (true) {
                val n = input.read(buffer)
                if (n < 0) break
                sha.update(buffer, 0, n)
            }
        }
        return sha.digest()
    }

    /** Whether [claimed] is [digest] written in hex or in Base64, which Google's hash fields might use. */
    private fun matches(digest: ByteArray, claimed: String): Boolean {
        val b64 = Base64.encodeToString(digest, Base64.NO_WRAP)
        return claimed.equals(digest.joinToString("") { "%02x".format(it) }, ignoreCase = true) ||
            claimed.trimEnd('=') == b64.trimEnd('=') ||
            claimed.trimEnd('=') == b64.trimEnd('=').replace('+', '-').replace('/', '_')
    }

    private fun <T> retry(block: () -> T): T {
        var attempt = 1
        while (true) try {
            return block()
        } catch (e: IOException) {
            if (attempt++ >= 4) throw e
            Thread.sleep(2_000L * attempt)
        }
    }

    /** The headers the Play Store sends to this endpoint (microG's set), for this phone's registration. */
    private fun headers(auth: AuthData): Map<String, String> {
        val device = auth.deviceInfoProvider!!
        return mapOf(
            "X-PS-RH" to requestHeader(BigInteger(auth.gsfId, 16).toLong(), device.properties),
            "User-Agent" to device.userAgentString,
            "Accept-Language" to "en-US",
            "Connection" to "Keep-Alive",
            "X-DFE-Device-Id" to auth.gsfId,
            "X-DFE-Client-Id" to "am-google",
            "X-DFE-Encoded-Targets" to TARGETS,
            "X-DFE-Phenotype" to PHENOTYPE,
            "Authorization" to "Bearer ${auth.authToken}",
            "Content-Type" to "application/x-protobuf",
        ) + listOfNotNull(
            // the registration Play made of this phone: not in the Play Store's own requests to this endpoint, but in Aurora's
            auth.deviceConfigToken.takeIf { it.isNotBlank() }?.let { "X-DFE-Device-Config-Token" to it },
            auth.deviceCheckInConsistencyToken.takeIf { it.isNotBlank() }?.let { "X-DFE-Device-Checkin-Consistency-Token" to it },
        )
    }

    private fun requestHeader(androidId: Long, build: java.util.Properties): String {
        val now = System.currentTimeMillis()
        fun Pb.stamp(ms: Long) = int(1, ms / 1000).int(2, ms % 1000 * 1_000_000)
        val timestamps = Pb()
            .msg(3) { str(1, java.lang.Long.toUnsignedString(androidId)).msg(2) { str(1, "${now}000").msg(2) { stamp(now) } } }
            .msg(6) { msg(1) { msg(1) { stamp(now) } }.msg(2) { stamp(now) } }.toBytes()
        val locality = Pb().int(2, 1).int(3, 2).str(4, "")
            .msg(8) { str(1, "").msg(2) { stamp(now) } }.msg(9) { str(1, "").msg(2) { stamp(now) } }.int(11, 0).toBytes()
        val model = build.getProperty("Build.MODEL").orEmpty()
        val header = Pb()
            .msg(1) { str(1, encode(gzip(timestamps))) }
            .msg(10) { msg(1) { str(1, "").str(2, "").str(3, "") } }
            .msg(11) { str(1, encode(locality)) }
            .msg(12) { int(1, 5) }
            .str(14, "")
            .msg(20) {
                msg(1) {
                    int(1, build.getProperty("Build.VERSION.SDK_INT").toLong()).str(2, build.getProperty("Build.ID").orEmpty())
                        .str(3, build.getProperty("Build.VERSION.RELEASE").orEmpty()).int(4, 0)
                }.str(2, "UnknownByte12{bytes=[size=0]}").int(3, 1) // as microG sends it
            }
            .msg(21) {
                str(1, build.getProperty("Build.DEVICE").orEmpty()).str(2, build.getProperty("Build.HARDWARE").orEmpty())
                    .str(3, model).str(4, FINSKY).str(5, model).int(6, androidId)
                    .str(7, build.getProperty("Build.FINGERPRINT").orEmpty())
            }
            .msg(27) { str(1, UUID.randomUUID().toString()).int(2, 2) }.toBytes()
        return encode(gzip(header))
    }

    private fun gzip(data: ByteArray) = ByteArrayOutputStream().also { out -> GZIPOutputStream(out).use { it.write(data) } }.toByteArray()

    private fun encode(data: ByteArray) = Base64.encodeToString(data, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)

    /** Just enough protobuf to speak to Play: write a message, and read one back as numbered fields. */
    private class Pb {
        private val out = ByteArrayOutputStream()

        private fun varint(value: Long) {
            var v = value
            while (v and 0x7F.inv().toLong() != 0L) {
                out.write(((v and 0x7F) or 0x80).toInt())
                v = v ushr 7
            }
            out.write(v.toInt())
        }

        fun int(field: Int, value: Long) = apply { varint((field shl 3).toLong()); varint(value) }
        fun bytes(field: Int, value: ByteArray) = apply {
            varint(((field shl 3) or 2).toLong())
            varint(value.size.toLong())
            out.write(value)
        }
        fun str(field: Int, value: String) = bytes(field, value.toByteArray())
        fun msg(field: Int, build: Pb.() -> Unit) = bytes(field, Pb().apply(build).toBytes())
        fun toBytes(): ByteArray = out.toByteArray()
    }

    private class Field(val number: Int, val value: Long, val bytes: ByteArray?) {
        fun text() = String(bytes!!)
        fun fields() = read(bytes!!)
    }

    private fun List<Field>.one(number: Int) = firstOrNull { it.number == number }
    private fun List<Field>.many(number: Int) = filter { it.number == number }

    /** A message's fields as text for the log: numbers, values, short strings, nested messages. */
    private fun dump(data: ByteArray, depth: Int = 0): String = try {
        read(data).joinToString(" ") { f ->
            val b = f.bytes
            when {
                b == null -> "${f.number}=${f.value}"
                b.isNotEmpty() && b.all { it.toInt() in 32..126 } -> "${f.number}=\"${String(b).take(60)}\""
                depth < 5 -> try { "${f.number}{${dump(b, depth + 1)}}" } catch (e: RuntimeException) { "${f.number}=<${b.size} bytes>" }
                else -> "${f.number}=<${b.size} bytes>"
            }
        }.take(1500)
    } catch (e: RuntimeException) {
        "<${data.size} bytes, not a message>"
    }

    private fun read(data: ByteArray): List<Field> {
        val fields = ArrayList<Field>()
        var i = 0
        fun varint(): Long {
            var shift = 0
            var result = 0L
            while (true) {
                val b = data[i++].toInt()
                result = result or ((b and 0x7F).toLong() shl shift)
                if ((b and 0x80) == 0) return result
                shift += 7
            }
        }
        while (i < data.size) {
            val tag = varint()
            val number = (tag ushr 3).toInt()
            when ((tag and 7).toInt()) {
                0 -> fields += Field(number, varint(), null)
                2 -> {
                    val n = varint().toInt()
                    fields += Field(number, 0, data.copyOfRange(i, i + n))
                    i += n
                }
                1 -> i += 8
                5 -> i += 4
                else -> throw IOException("not a protobuf message")
            }
        }
        return fields
    }
}

/** What the Google part did, for the player to copy into a bug report: no tokens, no headers. */
object PlayLog {
    fun write(context: Context, line: String) {
        val file = File(context.filesDir, "logs/play.log")
        file.parentFile?.mkdirs()
        if (file.length() > 200_000) file.delete()
        file.appendText("${java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.US).format(java.util.Date())} $line\n")
    }
}
