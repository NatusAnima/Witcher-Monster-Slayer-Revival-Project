package io.github.natusanima.slayerrevival

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
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

        fun dir(context: Context) = File(context.filesDir, "game/packs")

        fun complete(context: Context) = PlayPacks.expected(context).all { File(dir(context), it.name).length() == it.size }
    }

    @Volatile private var cancelled = false

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
        progress = -1
        thread(name = "pack-download") {
            download()
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
                    PlayPacks.fetch(this, auth, pack, dir(this)) { bytes ->
                        if (cancelled) throw CancellationException()
                        val done = before + bytes
                        progress = (done * 100 / total).toInt()
                        update("Downloading the extra data: ${size(done)} of ${size(total)} (pack ${i + 1} of ${packs.size})")
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
            update("The download stopped: ${e.message ?: e.javaClass.simpleName}")
        }
    }

    private fun size(bytes: Long) = Formatter.formatShortFileSize(this, bytes)

    private fun update(text: String) {
        status = text
        if (running) getSystemService(NotificationManager::class.java).notify(5, notification(text))
    }

    private fun notification(text: String, ongoing: Boolean = true): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("packs", "Extra data download", NotificationManager.IMPORTANCE_LOW))
        val cancel = PendingIntent.getService(this, 0, Intent(this, PackDownloadService::class.java).setAction(CANCEL),
            PendingIntent.FLAG_IMMUTABLE)
        val open = PendingIntent.getActivity(this, 0, Intent(this, SetupActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, "packs")
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle("Extra data")
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setProgress(if (ongoing) 100 else 0, progress.coerceAtLeast(0), ongoing && progress < 0)
            .setContentIntent(open)
            .setOngoing(ongoing)
            .apply { if (ongoing) addAction(Notification.Action.Builder(null, "Cancel", cancel).build()) }
            .build()
    }
}
