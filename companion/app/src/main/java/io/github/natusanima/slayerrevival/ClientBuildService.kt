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
import java.util.zip.CRC32
import java.util.zip.ZipFile
import kotlin.concurrent.thread

/**
 * Builds the playable client on the phone and installs it, with no PC and no adb. In order: assemble the APK from
 * the installed game and the extra data downloaded from Google Play (phone_build.py) → sign it (apksig) → the
 * player confirms removing the Play copy → the player confirms installing the client. Everything before the
 * removal is reversible, so the Play copy keeps working until then. The game hook travels inside the client's APK.
 *
 * When a release changes the game (Updates), the installed client is patched in place instead: the new hook and Gadget
 * go into a copy of it, signed with the same key and installed over it. No Google, no download, no uninstall.
 */
class ClientBuildService : Service() {
    companion object {
        const val INSTALL_RESULT = "io.github.natusanima.slayerrevival.CLIENT_INSTALL_RESULT"
        const val UNINSTALL_RESULT = "io.github.natusanima.slayerrevival.CLIENT_UNINSTALL_RESULT"
        /** Start extra: update the installed client in place instead of building one. */
        const val PATCH = "io.github.natusanima.slayerrevival.PATCH"

        /** An in-place update holds the installed client, the new copy, and Android's staged copy at once: about 2 GB each. */
        private const val PATCH_ROOM = 6L shl 30

        @Volatile var status: String? = null; private set
        @Volatile var progress = -1; private set
        @Volatile var running = false; private set

        /** True if the last run ended in a failure (not a cancel the player chose, not a success): the screens then offer a report. */
        @Volatile var failed = false; private set

        /** The confirmation screen Android is waiting on (removing or installing the game) until the player answers it. */
        @Volatile var pending: PendingIntent? = null; private set

        /** Opens the pending confirmation again: Android won't show it over another app, and a notification is the only other way in. */
        fun confirmNow() {
            try {
                pending?.send()
            } catch (_: PendingIntent.CanceledException) {
            }
        }

        /** A signed client is built but not installed yet (e.g. the install was cancelled): the build resumes there. */
        fun resumable(context: Context) = File(context.filesDir, "client/signed.apk").isFile

        private fun prefs(context: Context) = context.getSharedPreferences("client", Context.MODE_PRIVATE)

        /** The game version (Updates.gameVersion) of the app that built the installed client; clients built before it was recorded came from 0.1. */
        fun builtFor(context: Context) = prefs(context).getString("builtFor", "0.1")

        /** Called once a client of this app's game version is installed. */
        fun markBuilt(context: Context) =
            prefs(context).edit().putString("builtFor", Updates.gameVersion(Updates.installedVersion(context))).apply()

        /** True if the installed game carries this app's signature, so an update can go over it; null if it isn't installed. */
        fun signedByUs(context: Context): Boolean? {
            val info = try {
                context.packageManager.getPackageInfo(MainActivity.GAME, PackageManager.GET_SIGNING_CERTIFICATES)
            } catch (_: PackageManager.NameNotFoundException) {
                return null
            }
            val ours = ClientSigner.existingCertificate()?.encoded ?: return false // no key yet, so no client of ours
            return info.signingInfo?.apkContentsSigners.orEmpty().any { it.toByteArray().contentEquals(ours) }
        }

        /** True if the client was built for a game version other than [version]'s. Only means something for a client this app built. */
        fun builtForOther(context: Context, version: String) = builtFor(context) != Updates.gameVersion(version)

        /** True if the client this app built is installed but must be updated to carry the game of [version]. */
        fun staleFor(context: Context, version: String) = builtForOther(context, version) && signedByUs(context) == true

        /**
         * True if the installed client carries a different hook from the one this app ships, so a release that only fixes the
         * hook (a z release) is offered too. Compares the APK entry's CRC with the unpacked runtime's copy, and only once that
         * runtime belongs to this version of the app (it is unpacked when the server first starts); false when unsure.
         */
        fun hookChanged(context: Context): Boolean = try {
            val rt = Runtime.root(context)
            val version = context.packageManager.getPackageInfo(context.packageName, 0).lastUpdateTime.toString()
            val shipped = File(rt, "client/hook.bundle.js")
            if (File(rt, ".stamp").readText() != version || !shipped.isFile) false
            else ZipFile(context.packageManager.getApplicationInfo(MainActivity.GAME, 0).sourceDir).use { apk ->
                apk.getEntry("lib/arm64-v8a/libhook.js.so")?.let { it.crc != CRC32().apply { update(shipped.readBytes()) }.value }
            } ?: false
        } catch (_: Exception) {
            false
        }
    }

    // Not the cache folder: Android empties that when storage runs low, which is just when a 2 GB install needs room.
    private val work by lazy { File(filesDir, "client").apply { mkdirs() } }
    private val signed by lazy { File(work, "signed.apk") }

    override fun onBind(intent: Intent?) = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(3, notification(status ?: "Starting"), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        when (intent?.action) {
            UNINSTALL_RESULT -> handleUninstall(intent)
            INSTALL_RESULT -> handleInstall(intent)
            else -> if (!running) {
                running = true
                failed = false
                val patch = intent?.getBooleanExtra(PATCH, false) == true
                thread(name = "client-build") { awake { build(patch) } }
            }
        }
        return START_NOT_STICKY
    }

    private fun build(patch: Boolean) {
        try {
            if (patch) signed.delete() // an update the player cancelled earlier was built with the hook of an older release
            if (!signed.isFile && !assemble(patch)) return
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

    /**
     * Assembles and signs the client: from the installed game and the downloaded packs, or, with [patch], from the
     * installed client itself. False, with the reason shown, if it can't start.
     */
    private fun assemble(patch: Boolean): Boolean {
        val game = try {
            packageManager.getApplicationInfo(MainActivity.GAME, 0)
        } catch (_: PackageManager.NameNotFoundException) {
            finish("Install the game first (Setup step 2).")
            return false
        }
        if (patch) {
            if (foreignCopy()) {
                finish("The installed game was not built by this app, so it can't be updated in place. Run the guided setup again.")
                return false
            }
            if (filesDir.usableSpace < PATCH_ROOM) {
                finish("Free up about 6 GB, then tap Update the game again.")
                return false
            }
        } else if (!PackDownloadService.complete(this)) {
            finish("Download the extra data first (Setup step 4).")
            return false
        }
        update("Preparing", -1)
        val rt = Runtime.prepare(this)
        update(if (patch) "Updating the game (a few minutes)…" else "Building the client (a few minutes)…", -1)
        val unsigned = File(work, "unsigned.apk")
        val source = if (patch) listOf("--patch", game.sourceDir) else listOf(
            "--apks", File(game.sourceDir).parent!!, // the install dir holds base.apk and every split
            "--packs", PackDownloadService.dir(this).path)
        python(rt, "phone_build.py", source + listOf(
            "--gadget", "$rt/client/libgadget.so", "--hook", "$rt/client/hook.bundle.js",
            "--out", unsigned.path))
        update("Signing the client…", -1)
        val part = File(work, "signed.apk.part") // renamed once whole: a half-signed file must not look resumable
        ClientSigner.sign(unsigned, part)
        unsigned.delete()
        check(part.renameTo(signed)) { "could not keep the signed client" }
        if (!patch) PackDownloadService.dir(this).deleteRecursively() // the packs are inside the client now: free their 1.4 GB
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
    private fun foreignCopy() = signedByUs(this) == false

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
            PackageInstaller.STATUS_FAILURE_ABORTED -> finish("Cancelled: the game is still installed. Tap Install the client to try again.", failed = false)
            else -> finish("The game could not be removed: ${intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE)}")
        }
    }

    private fun handleInstall(intent: Intent) {
        when (outcome(intent)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> confirm(intent, "Confirm installing the client on screen.", 3)
            PackageInstaller.STATUS_SUCCESS -> thread(name = "client-cleanup") {
                markBuilt(this)
                signed.delete()
                finish("The client is installed. Tap Play.", failed = false)
            }
            PackageInstaller.STATUS_FAILURE_ABORTED -> finish("Cancelled: the client is not installed. Tap Install the client to try again.", failed = false)
            else -> finish(installFailure(intent))
        }
    }

    /** What Android's install failure codes usually mean on a phone, and what to do about it. */
    private fun installFailure(intent: Intent): String {
        val detail = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE).orEmpty()
        val advice = when (intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)) {
            PackageInstaller.STATUS_FAILURE_BLOCKED -> "Android blocked it. If Play Protect asks, tap More details, then Install anyway. " +
                "On a Samsung phone, turn off Auto Blocker (Settings, Security and privacy). In Brazil, Indonesia, Singapore and " +
                "Thailand Android's developer verification may be the cause; installing over adb avoids it."
            PackageInstaller.STATUS_FAILURE_CONFLICT -> "Another copy of the game is in the way. Remove it, then tap Install the client again."
            PackageInstaller.STATUS_FAILURE_INCOMPATIBLE -> "This phone cannot run it: it needs a 64-bit ARM phone with Android 11 or later."
            PackageInstaller.STATUS_FAILURE_INVALID -> "Android found the file damaged."
            PackageInstaller.STATUS_FAILURE_STORAGE -> "There is not enough free space. Free up about 6 GB, then tap Install the client again."
            else -> ""
        }
        return "The install failed: $detail $advice".trim()
    }

    /** The status Android reports. Once the player has answered, the notification that asked for the answer goes. */
    private fun outcome(intent: Intent): Int {
        val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)
        EventLog.write(this, "client", "Android answered with status $status: ${intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE)}")
        if (status != PackageInstaller.STATUS_PENDING_USER_ACTION) {
            pending = null
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
        pending = PendingIntent.getActivity(this, code, screen, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        update(text, -1)
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("confirm", "Confirm on screen", NotificationManager.IMPORTANCE_HIGH))
        manager.notify(6, Notification.Builder(this, "confirm")
            .setSmallIcon(android.R.drawable.stat_sys_warning)
            .setContentTitle("Confirm to continue")
            .setContentText(text)
            .setContentIntent(pending)
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

    /** Ends the run with [message]; [failed] says whether the screens should offer a bug report (a cancel or a success do not). */
    private fun finish(message: String, failed: Boolean = true) {
        Companion.failed = failed
        pending = null
        status = message
        progress = -1
        EventLog.write(this, "client", message)
        running = false
        val manager = getSystemService(NotificationManager::class.java)
        manager.cancel(6)
        stopForeground(STOP_FOREGROUND_DETACH)
        // the outcome stays, but as an ordinary notification: the build's own one is ongoing, with a spinner, and could not be swiped away
        manager.notify(3, notification(message, ongoing = false))
        stopSelf()
    }

    private fun update(text: String, p: Int) {
        status = text
        progress = p
        EventLog.write(this, "client", text)
        getSystemService(NotificationManager::class.java).notify(3, notification(text))
    }

    private fun notification(text: String, ongoing: Boolean = true): Notification {
        getSystemService(NotificationManager::class.java)
            .createNotificationChannel(NotificationChannel("client", "Client build", NotificationManager.IMPORTANCE_LOW))
        val open = pending ?: PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, "client")
            .setSmallIcon(if (ongoing) android.R.drawable.stat_sys_download else android.R.drawable.stat_sys_download_done)
            .setContentTitle(if (ongoing) "Building the client" else "The client build")
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .apply { if (ongoing) setProgress(100, 0, true) }
            .setContentIntent(open)
            .setOngoing(ongoing)
            .setAutoCancel(!ongoing)
            .build()
    }
}
