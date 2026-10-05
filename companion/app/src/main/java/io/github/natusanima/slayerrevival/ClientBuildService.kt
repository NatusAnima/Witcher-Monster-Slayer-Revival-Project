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
import android.text.format.Formatter
import io.github.muntashirakon.adb.AdbPairingRequiredException
import java.io.File
import java.security.MessageDigest
import kotlin.concurrent.thread

/**
 * Builds the playable client on the phone and installs it, with no PC. In order:
 * back up the game (the only way to reach its private asset packs) → extract the 26 packs → assemble the
 * APK (phone_build.py) → sign it (apksig) → replace the Play copy → push the game hook. Everything but the
 * final uninstall/install is reversible, so the Play copy keeps working until the very last step.
 */
class ClientBuildService : Service() {
    companion object {
        const val INSTALL_RESULT = "io.github.natusanima.slayerrevival.CLIENT_INSTALL_RESULT"
        const val HOOK_PATH = "/sdcard/Android/data/${MainActivity.GAME}/files/hook.js"

        @Volatile var status: String? = null; private set
        @Volatile var progress = -1; private set
        @Volatile var running = false; private set
        /** Set when the build can't start because Wireless debugging isn't paired yet; the UI offers to pair. */
        @Volatile var pairingRequired = false; private set

        /** A signed client is built but not installed yet (e.g. the install was cancelled): the build resumes there. */
        fun resumable(context: Context) = File(context.cacheDir, "client/signed.apk").isFile
    }

    private val work by lazy { File(cacheDir, "client").apply { mkdirs() } }
    private val signed by lazy { File(work, "signed.apk") }

    override fun onBind(intent: Intent?) = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(3, notification(status ?: "Starting"), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        if (intent?.action == INSTALL_RESULT) {
            handleInstall(intent)
        } else if (!running) {
            running = true
            pairingRequired = false
            thread(name = "client-build") { build() }
        }
        return START_NOT_STICKY
    }

    private fun build() {
        try {
            val game = try {
                packageManager.getApplicationInfo(MainActivity.GAME, 0)
            } catch (_: PackageManager.NameNotFoundException) {
                return finish("Install the game first (Setup step 2).")
            }
            update("Preparing", -1)
            val rt = Runtime.prepare(this)
            try {
                Adb.connect(this)
            } catch (e: AdbPairingRequiredException) {
                pairingRequired = true
                return finish(if (e is WirelessDebuggingOff) "Wireless debugging is off. Turn it on and pair this phone, then build again."
                else "Pair this phone with Wireless debugging, then build again.")
            }

            if (!signed.isFile) {
                val packs = File(work, "packs").apply { mkdirs() }
                val backup = File(work, "backup.ab")
                update("On your phone, tap “Back up my data” (leave the password empty).", -1)
                Adb.backup(this, MainActivity.GAME, backup) { bytes ->
                    update("Backing up the game: ${size(bytes)}", -1)
                }
                update("Extracting the game data…", -1)
                python(rt, "extract_packs.py", listOf(backup.path, packs.path))
                backup.delete()

                update("Building the client (a few minutes)…", -1)
                val unsigned = File(work, "unsigned.apk")
                val apks = File(game.sourceDir).parent!! // the install dir holds base.apk and every split
                python(rt, "phone_build.py", listOf(
                    "--apks", apks, "--packs", packs.path,
                    "--gadget", "$rt/client/libgadget.so", "--gadget-config", "$rt/client/libgadget.config.so",
                    "--out", unsigned.path))
                update("Signing the client…", -1)
                ClientSigner.sign(unsigned, signed)
                unsigned.delete()
                packs.deleteRecursively()
            }

            if (playSigned(MainActivity.GAME)) {
                update("Replacing the Play copy…", -1)
                Adb.uninstall(this, MainActivity.GAME)
            }
            update("Installing the client — confirm on screen.", -1)
            install(signed)
        } catch (e: Exception) {
            finish("The client build failed: ${e.message}")
        }
    }

    /** Runs one of the bundled builder scripts on the phone's Python; throws if it exits non-zero. */
    private fun python(rt: File, script: String, args: List<String>) {
        val log = File(filesDir, "logs/client-build.log")
        val process = Runtime.start(this, "libpython.so", listOf("$rt/client/$script") + args, log,
            mapOf("PYTHONHOME" to "$rt/python", "PYTHONUNBUFFERED" to "1"))
        val code = process.waitFor()
        if (code != 0) throw IllegalStateException("$script exited with code $code: see client-build.log")
    }

    private fun install(apk: File) {
        val installer = packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
        installer.openSession(installer.createSession(params)).use { session ->
            session.openWrite("client", 0, apk.length()).use { out ->
                apk.inputStream().use { it.copyTo(out) }
                session.fsync(out)
            }
            val done = Intent(this, ClientBuildService::class.java).setAction(INSTALL_RESULT)
            session.commit(PendingIntent.getService(this, 0, done,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE).intentSender)
        }
    }

    private fun handleInstall(intent: Intent) {
        when (intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION ->
                @Suppress("DEPRECATION") intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
                    ?.let { startActivity(it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
            PackageInstaller.STATUS_SUCCESS -> thread(name = "client-hook") {
                try {
                    update("Setting up the game hook…", -1)
                    val rt = Runtime.prepare(this)
                    Adb.push(this, File(rt, "client/hook.bundle.js").readBytes(), HOOK_PATH)
                    signed.delete()
                    finish("The client is installed. Tap Play.")
                } catch (e: Exception) {
                    finish("Installed, but the hook push failed: ${e.message}")
                }
            }
            else -> finish("The install failed: ${intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE)}")
        }
    }

    private fun playSigned(pkg: String): Boolean {
        val info = try {
            packageManager.getPackageInfo(pkg, PackageManager.GET_SIGNING_CERTIFICATES)
        } catch (_: PackageManager.NameNotFoundException) {
            return false
        }
        return info.signingInfo?.apkContentsSigners.orEmpty().any {
            MessageDigest.getInstance("SHA-256").digest(it.toByteArray())
                .joinToString("") { b -> "%02x".format(b) } == MainActivity.PLAY_CERT
        }
    }

    private fun size(bytes: Long) = Formatter.formatShortFileSize(this, bytes)

    private fun finish(message: String) {
        update(message, -1)
        running = false
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
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
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
