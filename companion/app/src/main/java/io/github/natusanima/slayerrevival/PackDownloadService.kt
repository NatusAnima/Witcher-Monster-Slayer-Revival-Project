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
import java.io.File
import java.io.IOException
import java.util.concurrent.CancellationException
import kotlin.concurrent.thread

/**
 * Downloads the game's 26 extra asset packs from Google Play (PlayPacks) in the foreground, so it carries on with
 * the screen off. The player is signed out of Google as soon as every pack is in and checked.
 */
class PackDownloadService : Service() {
    companion object {
        const val CANCEL = "io.github.natusanima.slayerrevival.CANCEL_PACKS"
        private const val CONNECTIONS = 4

        /** The running download's progress, or how the last one ended; null before the first. */
        @Volatile
        var status: String? = null
            private set

        /** Percent of all the packs, or -1 before the first bytes arrive. */
        @Volatile
        var progress = -1
            private set

        @Volatile
        var running = false
            private set

        /** True if the last run stopped on an error (not a cancel the player chose): the setup screen then offers a bug report. */
        @Volatile
        var failed = false
            private set

        fun dir(context: Context) = File(context.filesDir, "game/packs")

        fun complete(context: Context) = PlayPacks.expected(context).all { File(dir(context), it.name).length() == it.size }
    }

    @Volatile private var cancelled = false
    @Volatile private var shownAt = 0L
    @Volatile private var shownBytes = 0L
    private val cancelIntent by lazy {
        PendingIntent.getService(this, 0, Intent(this, PackDownloadService::class.java).setAction(CANCEL), PendingIntent.FLAG_IMMUTABLE)
    }
    private val openIntent by lazy { PendingIntent.getActivity(this, 0, Intent(this, SetupActivity::class.java), PendingIntent.FLAG_IMMUTABLE) }

    override fun onCreate() {
        super.onCreate()
        getSystemService(NotificationManager::class.java)
            .createNotificationChannel(NotificationChannel("packs", "Extra data download", NotificationManager.IMPORTANCE_LOW))
    }

    override fun onBind(intent: Intent?) = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == CANCEL) {
            cancelled = true
            if (!running) stopSelf()
            return START_NOT_STICKY
        }
        startForeground(5, notification(status?.takeIf { running } ?: "Starting"), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        if (running || intent == null) return START_NOT_STICKY
        running = true
        cancelled = false
        failed = false
        progress = -1
        shownAt = 0L
        shownBytes = 0L
        thread(name = "pack-download") {
            val release = keepAwake(this, "packs", 4 * 60 * 60 * 1000L)
            try {
                download()
            } finally {
                release()
            }
            running = false
            stopForeground(STOP_FOREGROUND_DETACH)
            getSystemService(NotificationManager::class.java).notify(5, notification(status.orEmpty(), ongoing = false)) // the outcome stays
            stopSelf()
        }
        return START_NOT_STICKY
    }

    private fun download() {
        try {
            val packs = PlayPacks.expected(this)
            val total = packs.sumOf { it.size }
            var before = 0L
            var synced = false
            for ((i, pack) in packs.withIndex()) {
                if (File(dir(this), pack.name).length() == pack.size) { // kept from an earlier run
                    before += pack.size
                    continue
                }
                var attempt = 1
                while (true) try {
                    val auth = PlayAccount.session(this) // a fresh access token for each pack: a long download outlives one
                    if (!synced) {
                        synced = true
                        try {
                            PlayPacks.sync(this, auth)
                        } catch (e: IOException) {
                            PlayLog.write(this, "device sync failed: $e") // the download is still tried
                        }
                    }
                    // parallel connections first; if Google refuses those, a single one
                    PlayPacks.fetch(this, auth, pack, dir(this), if (attempt == 1) CONNECTIONS else 1) { bytes ->
                        if (cancelled) throw CancellationException()
                        val done = before + bytes
                        progress = (done * 100 / total).toInt()
                        show(done, total, i, packs.size)
                    }
                    break
                } catch (e: IOException) {
                    PlayLog.write(this, "${pack.name} failed (attempt $attempt): $e")
                    if (attempt++ >= 2) throw e // once more on a fresh session: the download links may have expired
                }
                before += pack.size
            }
            PlayAccount.signOut(this)
            progress = 100
            update("All ${packs.size} packs are downloaded and checked. You are signed out of Google.")
        } catch (e: CancellationException) {
            update("Cancelled. Starting again continues where this stopped.")
        } catch (e: Exception) {
            PlayLog.write(this, "download stopped: $e")
            failed = true
            update("The download stopped: ${e.message ?: e.javaClass.simpleName}")
        }
    }

    /** The progress line, at most once a second: the bytes arrive far faster than a notification can be shown. */
    private fun show(done: Long, total: Long, index: Int, count: Int) {
        val now = SystemClock.elapsedRealtime()
        val last = shownAt // the download threads all call this: read it once, or another thread's update makes the divisor 0
        if (now - last < 1000) return
        val rate = if (last == 0L) 0 else maxOf(0L, done - shownBytes) * 1000 / (now - last)
        shownAt = now
        shownBytes = done
        update("Downloading the extra data: ${size(done)} of ${size(total)}" + (if (rate > 0) " · ${size(rate)}/s" else "") +
            " · pack ${index + 1} of $count")
    }

    private fun size(bytes: Long) = Formatter.formatShortFileSize(this, bytes)

    private fun update(text: String) {
        status = text
        EventLog.write(this, "packs", text)
        if (running) getSystemService(NotificationManager::class.java).notify(5, notification(text))
    }

    private fun notification(text: String, ongoing: Boolean = true): Notification {
        return Notification.Builder(this, "packs")
            .setSmallIcon(if (ongoing) android.R.drawable.stat_sys_download else android.R.drawable.stat_sys_download_done)
            .setContentTitle("Extra data")
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setProgress(if (ongoing) 100 else 0, progress.coerceAtLeast(0), ongoing && progress < 0)
            .setContentIntent(openIntent)
            .setOngoing(ongoing)
            .apply { if (ongoing) addAction(Notification.Action.Builder(null, "Cancel", cancelIntent).build()) }
            .build()
    }
}
