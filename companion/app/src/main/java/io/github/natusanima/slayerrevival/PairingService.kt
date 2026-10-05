package io.github.natusanima.slayerrevival

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.RemoteInput
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import io.github.muntashirakon.adb.android.AdbMdns
import kotlin.concurrent.thread

/**
 * Pairs the app with this phone's Wireless debugging. Android closes its pairing dialog as soon as the player
 * leaves Settings, so the 6-digit code can't be typed into this app's own screen. It is typed into a notification
 * instead, which can be answered with the dialog still open behind it. The pairing port is found over mDNS, so
 * the player never types an address.
 */
class PairingService : Service() {
    companion object {
        const val STOP = "io.github.natusanima.slayerrevival.STOP_PAIRING"
        private const val CODE = "code"
        private const val WAITING = "Open Wireless debugging in Settings and tap “Pair device with pairing code”."
        private const val READY = "Pull down this notification and type the 6-digit pairing code."

        /** What the pairing is waiting for, or how it ended; null before the first start. */
        @Volatile
        var status: String? = null
            private set
    }

    private var mdns: AdbMdns? = null
    @Volatile private var port = -1
    @Volatile private var pairing = false

    override fun onBind(intent: Intent?) = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        if (mdns == null) {
            port = -1
            status = WAITING
        }
        startForeground(4, notification(status ?: WAITING, port > 0), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        val code = intent?.let { RemoteInput.getResultsFromIntent(it) }?.getCharSequence(CODE)?.toString()?.trim()
        if (code != null) pair(code)
        else if (mdns == null) {
            // Called whenever the pairing dialog opens (a port) or closes (none), and again for each new code.
            mdns = AdbMdns(this, AdbMdns.SERVICE_TYPE_TLS_PAIRING) { _, found ->
                port = found
                if (!pairing) update(if (found > 0) READY else WAITING, found > 0)
            }.also { it.start() }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        mdns?.stop()
        mdns = null
        super.onDestroy()
    }

    private fun pair(code: String) {
        val target = port
        if (pairing) return
        if (target <= 0) return update("The pairing dialog isn't open. Tap “Pair device with pairing code” first.", false)
        pairing = true
        update("Pairing…", false)
        thread(name = "pair") {
            try {
                Adb.pair(this, "127.0.0.1", target, code)
                update("Paired. Building the client…", false)
                startForegroundService(Intent(this, ClientBuildService::class.java)) // it connects and reports its own errors
                stopSelf()
            } catch (e: Exception) {
                pairing = false
                update("Pairing failed: ${e.message ?: e.javaClass.simpleName}. Check the code in the dialog and enter it again.",
                    port > 0)
            }
        }
    }

    private fun update(text: String, reply: Boolean) {
        status = text
        getSystemService(NotificationManager::class.java).notify(4, notification(text, reply))
    }

    private fun notification(text: String, reply: Boolean): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("pairing", "Pairing", NotificationManager.IMPORTANCE_HIGH))
        val open = PendingIntent.getActivity(this, 0, Intent(this, PairActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val cancel = PendingIntent.getService(this, 1, Intent(this, PairingService::class.java).setAction(STOP),
            PendingIntent.FLAG_IMMUTABLE)
        val builder = Notification.Builder(this, "pairing")
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setContentTitle("Pair with Wireless debugging")
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setContentIntent(open)
            .setOngoing(true)
        if (reply) {
            val input = RemoteInput.Builder(CODE).setLabel("6-digit code").build()
            val answer = PendingIntent.getService(this, 2, Intent(this, PairingService::class.java),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE) // the reply is added to this intent
            builder.addAction(Notification.Action.Builder(null, "Enter code", answer).addRemoteInput(input).build())
        }
        return builder.addAction(Notification.Action.Builder(null, "Cancel", cancel).build()).build()
    }
}
