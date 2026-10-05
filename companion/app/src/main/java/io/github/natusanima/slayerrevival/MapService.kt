package io.github.natusanima.slayerrevival

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.PowerManager
import android.os.SystemClock
import android.text.format.Formatter
import java.io.File
import java.io.IOException
import kotlin.concurrent.thread

/**
 * Downloads a region's OpenStreetMap extract from Geofabrik and builds its map index on the phone with
 * osm_extract_index.py, in the foreground so it carries on with the screen off.
 */
class MapService : Service() {
    companion object {
        const val CANCEL = "io.github.natusanima.slayerrevival.CANCEL_MAP"

        /** The running build's progress, or how the last one ended; null before the first. */
        @Volatile
        var status: String? = null
            private set

        /** Percent of the download, or -1 while the size is unknown or the index is being built. */
        @Volatile
        var progress = -1
            private set

        @Volatile
        var running = false
            private set
    }

    @Volatile private var cancelled = false
    @Volatile private var builder: Process? = null

    override fun onBind(intent: Intent?) = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == CANCEL) {
            cancelled = true
            builder?.destroy()
            if (!running) stopSelf()
            return START_NOT_STICKY
        }
        startForeground(2, notification(status?.takeIf { running } ?: "Starting"), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        if (running || intent == null) return START_NOT_STICKY
        running = true
        cancelled = false
        progress = -1
        val id = intent.getStringExtra("id")!!
        val name = intent.getStringExtra("name")!!
        val url = intent.getStringExtra("url")!!
        thread(name = "map-build") {
            // the CPU would stall with the screen off, and the index builder runs for minutes
            val lock = getSystemService(PowerManager::class.java).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "slayerrevival:map")
                .apply { acquire(2 * 60 * 60 * 1000L) }
            try {
                build(id, name, url)
            } finally {
                lock.release()
            }
            running = false
            stopSelf()
        }
        return START_NOT_STICKY
    }

    private fun build(id: String, name: String, url: String) {
        val dir = Maps.dir(this)
        val pbf = File(dir, "$id.osm.pbf")
        val index = File(dir, "$id-features.sqlite")
        try {
            var shown = -2
            download(url, pbf) { done, total ->
                if (cancelled) throw IOException("cancelled")
                progress = if (total > 0) (done * 100 / total).toInt() else -1
                if (progress != shown) {
                    shown = progress
                    val of = if (total > 0) " of ${size(total)}" else ""
                    update("Downloading $name: ${size(done)}$of")
                }
            }
            progress = -1
            update("Building the map of $name. This takes a few minutes.")
            val rt = Runtime.prepare(this)
            val log = File(filesDir, "logs/map-build.log").apply { delete() }
            val process = Runtime.start(this, "libpython.so", listOf("$rt/maps/map-road-fixture-01/osm_extract_index.py",
                "--input", "$pbf", "--output", "$index"), log, mapOf("PYTHONHOME" to "$rt/python", "PYTHONUNBUFFERED" to "1"))
            builder = process
            // the builder prints nothing until it is done: show that it is alive, with the index growing beside it
            val started = SystemClock.elapsedRealtime()
            while (!process.waitFor(5, java.util.concurrent.TimeUnit.SECONDS)) {
                val minutes = (SystemClock.elapsedRealtime() - started) / 60_000
                val part = File(dir, "${index.name}.partial").length()
                update("Building the map of $name: $minutes min so far" + (if (part > 0) ", ${size(part)} written" else "") + ". This takes a few minutes.")
            }
            val code = process.exitValue()
            if (cancelled) throw IOException("cancelled")
            if (code != 0) throw IOException("the map builder stopped with code $code: see its log")
            Maps.select(this, index, name)
            update(if (ServerService.status == "Stopped") "$name is ready." else "$name is ready. Stop and start the server to load it.")
        } catch (e: Exception) {
            update(if (cancelled) "Cancelled." else "The map of $name failed: ${e.message}")
        } finally {
            builder = null
            pbf.delete()
            File(dir, "${index.name}.partial").delete()
        }
    }

    private fun size(bytes: Long) = Formatter.formatShortFileSize(this, bytes)

    private fun update(text: String) {
        status = text
        if (running) getSystemService(NotificationManager::class.java).notify(2, notification(text))
    }

    private fun notification(text: String): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("maps", "Map downloads", NotificationManager.IMPORTANCE_LOW))
        val cancel = PendingIntent.getService(this, 0, Intent(this, MapService::class.java).setAction(CANCEL),
            PendingIntent.FLAG_IMMUTABLE)
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, "maps")
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle("Map")
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setProgress(100, progress.coerceAtLeast(0), progress < 0)
            .setContentIntent(open)
            .setOngoing(true)
            .addAction(Notification.Action.Builder(null, "Cancel", cancel).build())
            .build()
    }
}
