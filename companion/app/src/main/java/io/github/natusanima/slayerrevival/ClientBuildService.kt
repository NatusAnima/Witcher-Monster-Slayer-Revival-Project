package io.github.natusanima.slayerrevival

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.PowerManager
import java.io.File
import kotlin.concurrent.thread

/**
 * Builds the playable client on the phone and installs it, with no PC and no adb. In order: assemble the APK from
 * the installed game and the extra data downloaded from Google Play (phone_build.py) → sign it (apksig) → the
 * player confirms removing the Play copy → the player confirms installing the client. Everything before the
 * removal is reversible, so the Play copy keeps working until then. The game hook travels inside the client's APK.
 */
class ClientBuildService : Service() {
    companion object {
        const val INSTALL_RESULT = "io.github.natusanima.slayerrevival.CLIENT_INSTALL_RESULT"
        const val UNINSTALL_RESULT = "io.github.natusanima.slayerrevival.CLIENT_UNINSTALL_RESULT"

        @Volatile var status: String? = null; private set
        @Volatile var progress = -1; private set
        @Volatile var running = false; private set

        /** A signed client is built but not installed yet (e.g. the install was cancelled): the build resumes there. */
        fun resumable(context: Context) = File(context.filesDir, "client/signed.apk").isFile
    }

    // Not the cache folder: Android empties that when storage runs low, which is just when a 2 GB install needs room.
    private val work by lazy { File(filesDir, "client").apply { mkdirs() } }
    private val signed by lazy { File(work, "signed.apk") }
    private var tap: PendingIntent? = null // opens the confirmation screen the player has yet to answer

    override fun onBind(intent: Intent?) = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(3, notification(status ?: "Starting"), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        when (intent?.action) {
            UNINSTALL_RESULT -> handleUninstall(intent)
            INSTALL_RESULT -> handleInstall(intent)
            else -> if (!running) {
                running = true
                thread(name = "client-build") { awake { build() } }
            }
        }
        return START_NOT_STICKY
    }

    private fun build() {
        try {
            if (!signed.isFile && !assemble()) return
            if (foreignCopy()) {
                update("Confirm removing the game on screen. The client you built replaces it.", -1)
                packageManager.packageInstaller.uninstall(MainActivity.GAME, result(UNINSTALL_RESULT, 1))
            } else {
                install()
            }
        } catch (e: Exception) {
            work.listFiles()?.filter { it != signed }?.forEach { it.delete() } // half-made files: gigabytes
            finish("The client build failed: ${e.message}")
        }
    }

    /** Assembles and signs the client from the installed game and the downloaded packs. False, with the reason shown, if it can't start. */
    private fun assemble(): Boolean {
        val game = try {
            packageManager.getApplicationInfo(MainActivity.GAME, 0)
        } catch (_: PackageManager.NameNotFoundException) {
            finish("Install the game first (Setup step 2).")
            return false
        }
        if (!PackDownloadService.complete(this)) {
            finish("Download the extra data first (Setup step 4).")
            return false
        }
        update("Preparing", -1)
        val rt = Runtime.prepare(this)
        update("Building the client (a few minutes)…", -1)
        val unsigned = File(work, "unsigned.apk")
        python(rt, "phone_build.py", listOf(
            "--apks", File(game.sourceDir).parent!!, // the install dir holds base.apk and every split
            "--packs", PackDownloadService.dir(this).path,
            "--gadget", "$rt/client/libgadget.so", "--hook", "$rt/client/hook.bundle.js",
            "--out", unsigned.path))
        update("Signing the client…", -1)
        val part = File(work, "signed.apk.part") // renamed once whole: a half-signed file must not look resumable
        ClientSigner.sign(unsigned, part)
        unsigned.delete()
        check(part.renameTo(signed)) { "could not keep the signed client" }
        PackDownloadService.dir(this).deleteRecursively() // the packs are inside the client now: free their 1.4 GB
        return true
    }

    /** Runs one of the bundled builder scripts on the phone's Python; throws if it exits non-zero. */
    private fun python(rt: File, script: String, args: List<String>) {
        val log = File(filesDir, "logs/client-build.log")
        val process = Runtime.start(this, "libpython.so", listOf("$rt/client/$script") + args, log,
            mapOf("PYTHONHOME" to "$rt/python", "PYTHONUNBUFFERED" to "1"))
        val code = process.waitFor()
        if (code != 0) throw IllegalStateException("$script exited with code $code: see client-build.log")
    }

    /** The game is installed but not signed with this app's key (the Play copy, say): Android won't update it, so it has to go first. */
    private fun foreignCopy(): Boolean {
        val info = try {
            packageManager.getPackageInfo(MainActivity.GAME, PackageManager.GET_SIGNING_CERTIFICATES)
        } catch (_: PackageManager.NameNotFoundException) {
            return false
        }
        val ours = ClientSigner.certificate().encoded
        return info.signingInfo?.apkContentsSigners.orEmpty().none { it.toByteArray().contentEquals(ours) }
    }

    private fun install() {
        update("Passing the client to Android…", -1)
        val installer = packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
        installer.openSession(installer.createSession(params)).use { session ->
            session.openWrite("client", 0, signed.length()).use { out ->
                signed.inputStream().use { it.copyTo(out) }
                session.fsync(out)
            }
            session.commit(result(INSTALL_RESULT, 0))
        }
    }

    /** Where Android reports back to this service. */
    private fun result(action: String, code: Int) = PendingIntent.getService(this, code,
        Intent(this, ClientBuildService::class.java).setAction(action),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE).intentSender

    private fun handleUninstall(intent: Intent) {
        when (outcome(intent)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> confirm(intent, "Confirm removing the game on screen. The client replaces it.", 2)
            PackageInstaller.STATUS_SUCCESS -> thread(name = "client-install") {
                awake {
                    try {
                        install()
                    } catch (e: Exception) {
                        finish("The install failed: ${e.message}")
                    }
                }
            }
            PackageInstaller.STATUS_FAILURE_ABORTED -> finish("Cancelled: the game is still installed. Tap Install the client to try again.")
            else -> finish("The game could not be removed: ${intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE)}")
        }
    }

    private fun handleInstall(intent: Intent) {
        when (outcome(intent)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> confirm(intent, "Confirm installing the client on screen.", 3)
            PackageInstaller.STATUS_SUCCESS -> thread(name = "client-cleanup") {
                signed.delete()
                finish("The client is installed. Tap Play.")
            }
            PackageInstaller.STATUS_FAILURE_ABORTED -> finish("Cancelled: the client is not installed. Tap Install the client to try again.")
            else -> finish("The install failed: ${intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE)}")
        }
    }

    /** The status Android reports. Once the player has answered, the notification that asked for the answer goes. */
    private fun outcome(intent: Intent): Int {
        val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)
        if (status != PackageInstaller.STATUS_PENDING_USER_ACTION) {
            tap = null
            getSystemService(NotificationManager::class.java).cancel(6)
        }
        return status
    }

    /**
     * Opens the confirmation screen Android asks for. It can't open over another app or a dark screen, so
     * notifications offer it as well: tapping either reopens it if it was dismissed.
     */
    private fun confirm(result: Intent, text: String, code: Int) {
        @Suppress("DEPRECATION") val screen = result.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
            ?: return finish("Android gave no confirmation screen to show.")
        screen.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        tap = PendingIntent.getActivity(this, code, screen, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        update(text, -1)
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("confirm", "Confirm on screen", NotificationManager.IMPORTANCE_HIGH))
        manager.notify(6, Notification.Builder(this, "confirm")
            .setSmallIcon(android.R.drawable.stat_sys_warning)
            .setContentTitle("Confirm to continue")
            .setContentText(text)
            .setContentIntent(tap)
            .setAutoCancel(true)
            .build())
        startActivity(screen)
    }

    /** The CPU would stall with the screen off, so a long job holds a wake lock. */
    private fun <T> awake(job: () -> T): T {
        val lock = getSystemService(PowerManager::class.java).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "slayerrevival:client")
        lock.acquire(60 * 60 * 1000L)
        try {
            return job()
        } finally {
            lock.release()
        }
    }

    private fun finish(message: String) {
        update(message, -1)
        running = false
        getSystemService(NotificationManager::class.java).cancel(6)
        stopForeground(STOP_FOREGROUND_DETACH)
        stopSelf()
    }

    private fun update(text: String, p: Int) {
        status = text
        progress = p
        getSystemService(NotificationManager::class.java).notify(3, notification(text))
    }

    private fun notification(text: String): Notification {
        getSystemService(NotificationManager::class.java)
            .createNotificationChannel(NotificationChannel("client", "Client build", NotificationManager.IMPORTANCE_LOW))
        val open = tap ?: PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, "client")
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle("Building the client")
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setProgress(100, 0, true)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
    }
}
