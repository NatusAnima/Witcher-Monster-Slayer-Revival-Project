package io.github.natusanima.slayerrevival

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.SystemClock
import android.text.format.Formatter
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/**
 * Downloads a region's OpenStreetMap extract from Geofabrik and builds its map index on the phone with
 * osm_extract_index.py, in the foreground so it carries on with the screen off. A dropped connection resumes, a failed build keeps
 * the download, and how it ended is kept (Maps.failure) so the screens can say what happened and offer to try again.
 */
class MapService : Service() {
    companion object {
        const val CANCEL = "io.github.natusanima.slayerrevival.CANCEL_MAP"

        /** The running build's progress, or how the last one ended; null before the first. */
        @Volatile
        var status: String? = null
            private set

        /** Percent of the download or of the build, or -1 while there is nothing to measure yet. */
        @Volatile
        var progress = -1
            private set

        @Volatile
        var running = false
            private set

        /** True if the last run ended in a failure (not a cancel the player chose): the screens then offer a report. */
        @Volatile
        var failed = false
            private set

        /** Builds the map for [request], carrying on from a kept download if there is one. */
        fun start(context: Context, request: Maps.Request) {
            context.startForegroundService(Intent(context, MapService::class.java).putExtra("id", request.id)
                .putExtra("name", request.name).putExtra("url", request.url).putExtra("low", request.lowMemory))
        }
    }

    /** A failure whose message is already in words for the player. */
    private class Failure(message: String) : Exception(message)

    @Volatile private var cancelled = false
    @Volatile private var builder: Process? = null
    private var lastLogged = 0L
    private var lastPhase = ""

    override fun onBind(intent: Intent?) = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == CANCEL) {
            cancelled = true
            builder?.destroy()
            if (!running) stopSelf()
            return START_NOT_STICKY
        }
        startForeground(2, notification(status?.takeIf { running } ?: "Starting"), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        if (running || intent == null) {
            if (running) EventLog.write(this, "map", "ignored a second request: a map is already being built")
            return START_NOT_STICKY
        }
        running = true
        cancelled = false
        failed = false
        progress = -1
        val request = Maps.Request(intent.getStringExtra("id")!!, intent.getStringExtra("name")!!, intent.getStringExtra("url")!!,
            intent.getBooleanExtra("low", false))
        Maps.setRequest(this, request)
        Maps.setFailure(this, null)
        thread(name = "map-build") {
            build(request)
            running = false
            stopForeground(STOP_FOREGROUND_DETACH)
            getSystemService(NotificationManager::class.java).notify(2, notification(status.orEmpty(), ongoing = false)) // the outcome stays
            stopSelf()
        }
        return START_NOT_STICKY
    }

    private fun build(request: Maps.Request) {
        val dir = Maps.dir(this)
        val pbf = File(dir, "${request.id}.osm.pbf")
        val part = File(dir, "${request.id}.osm.pbf.part")
        val saved = File(dir, "${request.id}.osm.pbf.url") // the dated file the part comes from, so a resume asks the same one
        val index = File(dir, "${request.id}-features.sqlite")
        // the builder never overwrites, so a rebuild goes here and the old map stays until the new one is done
        val fresh = File(dir, "${index.name}.new")
        var release = {}
        EventLog.write(this, "map", "starting ${request.name} (${request.id}), low-memory mode ${request.lowMemory}")
        try {
            Maps.sweep(this)
            listOf(fresh, File(dir, "${fresh.name}.partial"), File(dir, "${fresh.name}.nodes")).forEach { it.delete() }
            val extract = if (pbf.isFile) null else resolve(request, part, saved)
            val bytes = extract?.bytes ?: pbf.length()
            // a 1 GB extract can take longer than a fixed lock lasts
            release = keepAwake(this, "map", maxOf(2 * 3_600_000L, bytes / 1_048_576 * 8_000))
            val have = if (extract == null) bytes else part.length()
            val need = Maps.diskNeeded(bytes, request.lowMemory, Maps.selected(this)?.length() ?: 0) - have
            if (filesDir.usableSpace < need) {
                throw Failure("There is not enough free space for the map of ${request.name}: it needs about ${size(need)} more and " +
                    "this phone has ${size(filesDir.usableSpace)} free. Free up space and tap Try again (what is downloaded is kept), " +
                    "or pick a smaller region.")
            }
            if (extract != null) {
                download(request, extract, part)
                if (!part.renameTo(pbf)) throw IOException("the download could not be kept")
                saved.delete()
            }
            buildIndex(request, pbf, fresh, bytes)
            index.delete()
            if (!fresh.renameTo(index)) throw IOException("the new map could not replace the old one")
            Maps.select(this, index, request.name)
            pbf.delete()
            part.delete()
            saved.delete()
            Maps.setRequest(this, null)
            progress = 100
            update(if (ServerService.reloadMap(this)) "${request.name} is ready. The running server is loading it." else
                "${request.name} is ready.", "end")
        } catch (e: Failure) {
            fail(e.message!!)
        } catch (e: Exception) {
            if (cancelled) {
                update("Cancelled. Try again carries on from what was downloaded.", "end")
            } else {
                fail("The map of ${request.name} stopped: ${e.message ?: e.javaClass.simpleName}. What is downloaded (${size(part.length() + pbf.length())}) " +
                    "is kept: tap Try again.")
            }
        } finally {
            builder = null
            listOf(fresh, File(dir, "${fresh.name}.partial"), File(dir, "${fresh.name}.nodes")).forEach { it.delete() }
            release()
        }
    }

    /** Asks Geofabrik for the dated file behind the region's link, or for the one an earlier try was downloading. */
    private fun resolve(request: Maps.Request, part: File, saved: File): Geofabrik.Extract {
        update("Asking Geofabrik about ${request.name}…", "ask")
        saved.takeIf { it.isFile && part.isFile }?.let { kept ->
            try {
                return Geofabrik.resolve(kept.readText())
            } catch (e: Geofabrik.Limited) {
                throw e
            } catch (e: IOException) { // the dated file is gone: start over from today's
                EventLog.write(this, "map", "the saved download is gone (${e.message}): starting over")
            }
        }
        part.delete()
        val extract = Geofabrik.resolve(request.url)
        saved.parentFile?.mkdirs()
        saved.writeText(extract.url)
        return extract
    }

    private fun download(request: Maps.Request, extract: Geofabrik.Extract, part: File) {
        val started = part.length()
        val begun = SystemClock.elapsedRealtime()
        var shownAt = 0L
        var shownBytes = started
        var rate = 0L
        Geofabrik.download(extract.url, part, extract.bytes, { done ->
            val now = SystemClock.elapsedRealtime()
            if (now - shownAt >= 1000) {
                val instant = if (shownAt == 0L) 0 else maxOf(0L, done - shownBytes) * 1000 / (now - shownAt)
                rate = if (rate == 0L) instant else (rate * 7 + instant * 3) / 10 // a moving average, so the time left follows the connection
                shownAt = now
                shownBytes = done
                progress = if (extract.bytes > 0) (done * 100 / extract.bytes).toInt() else -1
                val left = if (rate > 0 && extract.bytes > done) ", ${Maps.duration((extract.bytes - done) / rate)} left" else ""
                update("Downloading ${request.name}: ${size(done)} of ${size(extract.bytes)}" +
                    (if (rate > 0) " · ${size(rate)}/s" else "") + left, "download")
            }
        }, { cancelled })
        EventLog.write(this, "map", "downloaded ${size(extract.bytes - started)} in ${(SystemClock.elapsedRealtime() - begun) / 1000} s")
    }

    private fun buildIndex(request: Maps.Request, pbf: File, fresh: File, bytes: Long) {
        progress = -1
        update("Preparing the map builder…", "prepare")
        val rt = Runtime.prepare(this)
        if (cancelled) throw IOException("cancelled")
        val log = File(filesDir, "logs/map-build.log").apply { delete() }
        val args = listOf("$rt/maps/map-road-fixture-01/osm_extract_index.py", "--input", "$pbf", "--output", "$fresh") +
            (if (request.lowMemory) listOf("--low-memory") else emptyList())
        val process = Runtime.start(this, "libpython.so", args, log, mapOf("PYTHONHOME" to "$rt/python", "PYTHONUNBUFFERED" to "1"))
        builder = process
        val estimate = Maps.buildTime(bytes)
        update("Reading the map of ${request.name}. The whole build takes $estimate.", "reading")
        val started = SystemClock.elapsedRealtime()
        // the builder prints a progress line every 2 s once it is past the node phase; before that only the clock tells it is alive
        while (!process.waitFor(2, TimeUnit.SECONDS)) {
            val line = progressLine(log)
            if (line == null) {
                update("Reading the map of ${request.name} (${(SystemClock.elapsedRealtime() - started) / 60_000} min so far). " +
                    "The whole build takes $estimate.", "reading")
            } else {
                val percent = line.optDouble("percent", -1.0)
                progress = if (percent >= 0) percent.toInt() else -1
                val left = if (line.has("eta")) "${Maps.duration(line.getLong("eta"))} left" else "$estimate in all"
                update("Building the map of ${request.name}: " + (if (percent >= 0) "${percent.toInt()}% · " else "") + left +
                    " · ${line.optInt("roads") + line.optInt("areas")} features · map ${line.optInt("index_mb")} MB · " +
                    "memory ${line.optInt("rss_anon_mb")} MB", "features")
            }
        }
        if (cancelled) throw IOException("cancelled")
        val code = process.exitValue()
        EventLog.write(this, "map", "the builder ended with code $code after ${(SystemClock.elapsedRealtime() - started) / 1000} s")
        if (code != 0) throw Failure(builderFailure(code, log, request))
    }

    /** What an exit of the map builder means, and what to do: the commonest ends are Android killing it for memory, and a full disk. */
    private fun builderFailure(code: Int, log: File, request: Maps.Request): String {
        val again = "Tap Try again (the download is kept)"
        val slow = !request.lowMemory
        if (code == 3 || code == 137) {
            if (slow) Maps.setRequest(this, request.copy(lowMemory = true)) // the next try keeps the node data on disk
            return (if (code == 3) "The map of ${request.name} needs more memory than this phone has." else
                "Android stopped the map builder, almost certainly because the phone ran out of memory.") +
                (if (slow) " $again: it will use a slower mode that needs far less memory. Or pick a smaller region."
                else " Even the slower mode ran out, so pick a smaller region.")
        }
        if (code == 4 || code == 135) {
            return "The disk filled up while building the map of ${request.name}. Free up space. $again, or pick a smaller region."
        }
        return "The map builder stopped with code $code. Last line of its log: ${lastLine(log)}. Tap Send a report if it keeps happening."
    }

    /** The newest PROGRESS line the builder printed, from the end of its log. */
    private fun progressLine(log: File): JSONObject? = try {
        tail(log).lineSequence().lastOrNull { it.startsWith("PROGRESS ") }?.removePrefix("PROGRESS ")?.let { JSONObject(it) }
    } catch (_: Exception) {
        null
    }

    private fun lastLine(log: File) = tail(log).lineSequence().lastOrNull { it.isNotBlank() && !it.startsWith("PROGRESS ") }
        ?.take(300) ?: "empty"

    private fun tail(file: File): String = try {
        RandomAccessFile(file, "r").use { f ->
            val data = ByteArray(minOf(f.length(), 8192L).toInt())
            f.seek(f.length() - data.size)
            f.readFully(data)
            String(data)
        }
    } catch (_: Exception) {
        ""
    }

    private fun fail(message: String) {
        failed = true
        Maps.setFailure(this, message)
        update(message, "end")
    }

    private fun size(bytes: Long) = Formatter.formatShortFileSize(this, bytes)

    /** Sets the status and the notification; the log keeps a line when the phase changes and every 30 s, not every second. */
    private fun update(text: String, phase: String = "") {
        status = text
        val now = SystemClock.elapsedRealtime()
        if (phase != lastPhase || now - lastLogged >= 30_000) {
            lastPhase = phase
            lastLogged = now
            EventLog.write(this, "map", text)
        }
        if (running) getSystemService(NotificationManager::class.java).notify(2, notification(text))
    }

    private fun notification(text: String, ongoing: Boolean = true): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("maps", "Map downloads", NotificationManager.IMPORTANCE_LOW))
        val cancel = PendingIntent.getService(this, 0, Intent(this, MapService::class.java).setAction(CANCEL),
            PendingIntent.FLAG_IMMUTABLE)
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, "maps")
            .setSmallIcon(if (ongoing) android.R.drawable.stat_sys_download else android.R.drawable.stat_sys_download_done)
            .setContentTitle("Map")
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setProgress(if (ongoing) 100 else 0, progress.coerceAtLeast(0), ongoing && progress < 0)
            .setContentIntent(open)
            .setOngoing(ongoing)
            .apply { if (ongoing) addAction(Notification.Action.Builder(null, "Cancel", cancel).build()) }
            .build()
    }
}
