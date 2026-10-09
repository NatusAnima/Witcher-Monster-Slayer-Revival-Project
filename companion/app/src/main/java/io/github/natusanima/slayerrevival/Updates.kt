package io.github.natusanima.slayerrevival

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import org.json.JSONObject
import java.io.File
import java.net.URL
import kotlin.concurrent.thread

/**
 * Self-update: the newest GitHub release's APK, installed over this app through Android's package installer.
 *
 * Versions are x.y.z. x is the stage (alpha, beta, ...). y changes only with a release that touches the game
 * itself: the installed game is then updated in place (ClientBuildService). z is for changes to this app alone,
 * which leave the game as it is.
 */
object Updates {
    const val REPO = "NatusAnima/Witcher-Monster-Slayer-Revival-Project"

    /** [game]: installing it leaves the game built by this app out of date, so it must be updated too. */
    class Release(val version: String, val apk: String, val game: Boolean)

    /** A release newer than this app, once the check has found one. */
    @Volatile
    var latest: Release? = null
        private set

    /** The download's progress, or why the update failed. */
    @Volatile
    var status: String? = null
        private set

    @Volatile
    var busy = false
        private set

    private var checked = false

    fun installedVersion(context: Context) = context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: "0"

    /** Looks for a newer release, once per app start. */
    fun check(context: Context) {
        if (checked) return
        checked = true
        val current = installedVersion(context)
        thread(name = "update-check") {
            try {
                val release = JSONObject(URL("https://api.github.com/repos/$REPO/releases/latest").readText())
                val version = release.getString("tag_name").removePrefix("v")
                val assets = release.getJSONArray("assets")
                val apk = (0 until assets.length()).map { assets.getJSONObject(it) }
                    .firstOrNull { it.getString("name").endsWith(".apk") } ?: return@thread
                if (newer(version, current)) {
                    latest = Release(version, apk.getString("browser_download_url"), ClientBuildService.staleFor(context, version))
                }
            } catch (_: Exception) {
                // offline, or GitHub's rate limit: the next start checks again
            }
        }
    }

    /** The numbers of a version. A tag may carry a suffix after a dash (v0.1.0-alpha): it is not part of the order. */
    private fun numbers(version: String) = version.substringBefore('-').split('.').map { it.toIntOrNull() ?: 0 }

    /** True if dotted version [a] is newer than [b]. */
    fun newer(a: String, b: String): Boolean {
        val x = numbers(a)
        val y = numbers(b)
        for (i in 0 until maxOf(x.size, y.size)) {
            val d = x.getOrElse(i) { 0 } - y.getOrElse(i) { 0 }
            if (d != 0) return d > 0
        }
        return false
    }

    /** The part of a version that names its game: x.y. Two versions with the same one carry the same game. */
    fun gameVersion(version: String) = numbers(version).take(2).joinToString(".")

    /** Downloads the release and hands it to the installer, which asks the player to confirm (MainActivity.INSTALL). */
    fun install(context: Context) {
        val release = latest ?: return
        if (busy) return
        busy = true
        status = "Downloading"
        thread(name = "update") {
            val apk = File(context.cacheDir, "update.apk")
            try {
                download(release.apk, apk) { done, total -> if (total > 0) status = "Downloading: ${done * 100 / total}%" }
                status = "Installing"
                val installer = context.packageManager.packageInstaller
                val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
                installer.openSession(installer.createSession(params)).use { session ->
                    session.openWrite("update.apk", 0, apk.length()).use { out ->
                        apk.inputStream().use { it.copyTo(out) }
                        session.fsync(out)
                    }
                    val done = Intent(context, MainActivity::class.java).setAction(MainActivity.INSTALL)
                    session.commit(PendingIntent.getActivity(context, 0, done,
                        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE).intentSender)
                }
            } catch (e: Exception) {
                finished("The update failed: ${e.message}")
            } finally {
                apk.delete()
            }
        }
    }

    /** The installer's answer when the player declined or it failed; on success Android replaces and closes the app. */
    fun finished(message: String?) {
        status = message
        busy = false
    }
}
