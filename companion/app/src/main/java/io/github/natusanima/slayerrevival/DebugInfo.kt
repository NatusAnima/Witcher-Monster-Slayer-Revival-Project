package io.github.natusanima.slayerrevival

import android.app.Activity
import android.app.ActivityManager
import android.app.AlertDialog
import android.app.ApplicationExitInfo
import android.app.NotificationManager
import android.content.ActivityNotFoundException
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.PowerManager
import android.os.StatFs
import android.provider.MediaStore
import android.system.Os
import android.system.OsConstants
import android.text.format.Formatter
import android.webkit.WebView
import android.widget.Toast
import java.io.File
import java.io.RandomAccessFile
import java.net.InetAddress
import java.net.ServerSocket
import java.security.MessageDigest
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.concurrent.TimeUnit
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import kotlin.concurrent.thread

/**
 * What a bug report carries: this phone, the game's install, the app's exit history and every log. No tokens are in them,
 * and emails, long token-like strings and coordinate pairs are masked on the way out anyway. A report is one zip saved in
 * Downloads and offered to the share sheet, so the whole of it travels (a chat or the clipboard holds far less). Nothing
 * leaves the phone until the player picks where to send it.
 */
object DebugInfo {
    private const val TAIL = 2_000_000
    private const val ISSUE_CHARS = 5_000

    // .prev logs are the runs before the last start: a restart would otherwise wipe the log of the crashed session.
    private val LOGS = listOf("events", "events.prev", "play", "client-build", "map-build", "server", "server.prev", "server.prev2",
        "tiles", "tiles.prev", "placement", "placement.prev", "game", "game.prev")

    private val EMAIL = Regex("[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}")
    private val TOKEN = Regex("[A-Za-z0-9_./+=-]{100,}")
    private val COORDINATES = Regex("-?\\d{1,3}\\.\\d{4,}\\s*[,; ]\\s*-?\\d{1,3}\\.\\d{4,}")

    fun installed(context: Context, name: String): PackageInfo? = try {
        context.packageManager.getPackageInfo(name, PackageManager.GET_SIGNING_CERTIFICATES)
    } catch (_: PackageManager.NameNotFoundException) {
        null
    }

    fun playSigned(info: PackageInfo) = info.signingInfo?.apkContentsSigners.orEmpty().any { signer ->
        MessageDigest.getInstance("SHA-256").digest(signer.toByteArray()).joinToString("") { "%02x".format(it) } == MainActivity.PLAY_CERT
    }

    /** Says what a report holds, then saves it in Downloads and opens the share sheet for it. */
    fun share(activity: Activity) {
        AlertDialog.Builder(activity)
            .setTitle("Send a report")
            .setMessage("The report is a zip saved in Downloads: your phone's model and versions, the game's install state, why the " +
                "app last stopped, and the app's logs. Emails and coordinates are masked and it holds no passwords. Nothing is sent " +
                "until you choose where.\n\nIf the game crashed or closed by itself, open it once more first and wait a minute: it " +
                "reports why it closed when it starts again.")
            .setPositiveButton("Make the report") { _, _ -> make(activity) }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    /** Saves the report in Downloads and opens the share sheet for it. Shows why if it can't. */
    private fun make(activity: Activity) {
        Toast.makeText(activity, "Making the report…", Toast.LENGTH_SHORT).show()
        thread(name = "report") {
            val made = try {
                save(activity)
            } catch (e: Exception) {
                EventLog.write(activity, "report", "failed: $e")
                null
            }
            activity.runOnUiThread {
                if (made == null) {
                    Toast.makeText(activity, "The report could not be made: see the events log.", Toast.LENGTH_LONG).show()
                    return@runOnUiThread
                }
                val send = Intent(Intent.ACTION_SEND).setType("application/zip").putExtra(Intent.EXTRA_STREAM, made.first)
                    .putExtra(Intent.EXTRA_SUBJECT, "Witcher Monster Slayer Revival report")
                    .putExtra(Intent.EXTRA_TEXT, "Report from ${Build.MODEL}, app ${Updates.installedVersion(activity)}. What happened:\n")
                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                Toast.makeText(activity, "Saved in Downloads as ${made.second}. Send it to the maintainers: it has your phone's model, " +
                    "versions and the app's logs, no passwords.", Toast.LENGTH_LONG).show()
                try {
                    activity.startActivity(Intent.createChooser(send, "Send the report"))
                } catch (_: ActivityNotFoundException) {
                }
            }
        }
    }

    /** Opens GitHub's new-issue page with the phone's details; the report file is attached by hand (the issue is public). */
    fun issue(context: Context) {
        val title = "Bug report: app ${Updates.installedVersion(context)}, Android ${Build.VERSION.RELEASE}, ${Build.MODEL}"
        val body = "**What happened?**\n\n\n**Phone and game**\n```\n${mask(header(context)).take(ISSUE_CHARS)}\n```\n\n" +
            "Attach the report file from Downloads (the app's Send a report button makes it). Issues here are public.\n"
        val page = Uri.parse("https://github.com/${Updates.REPO}/issues/new").buildUpon()
            .appendQueryParameter("title", title).appendQueryParameter("body", body).build()
        try {
            context.startActivity(Intent(Intent.ACTION_VIEW, page))
        } catch (_: ActivityNotFoundException) {
            Toast.makeText(context, "No browser to open GitHub with.", Toast.LENGTH_LONG).show()
        }
    }

    /** Builds the zip through MediaStore (no permission, no extra library). Returns its URI and name. */
    private fun save(context: Context): Pair<Uri, String> {
        val name = "witcher-revival-report-${SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(Date())}.zip"
        val resolver = context.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, name)
            put(MediaStore.Downloads.MIME_TYPE, "application/zip")
            put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
            put(MediaStore.Downloads.IS_PENDING, 1)
        }
        val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values) ?: error("Downloads would not take the file")
        try {
            ZipOutputStream(resolver.openOutputStream(uri) ?: error("could not write to Downloads")).use { zip ->
                fun add(entry: String, text: String) {
                    zip.putNextEntry(ZipEntry(entry))
                    zip.write(mask(text).toByteArray())
                    zip.closeEntry()
                }
                add("report.txt", header(context) + "\nApp exits, newest first:\n" + exits(context) + "\n\n" +
                    "Made on the phone and not sent anywhere. Emails, long token-like strings and coordinate pairs are masked.\n")
                add("logcat.txt", logcat())
                for (log in LOGS) {
                    val file = File(context.filesDir, "logs/$log.log")
                    if (file.isFile) add("logs/$log.log", collapse(tail(file, TAIL)))
                }
            }
            resolver.update(uri, ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) }, null, null)
        } catch (e: Exception) {
            resolver.delete(uri, null, null)
            throw e
        }
        EventLog.write(context, "report", "saved $name")
        return uri to name
    }

    private fun header(context: Context) = buildString {
        val pm = context.packageManager
        val activities = context.getSystemService(ActivityManager::class.java)
        val memory = ActivityManager.MemoryInfo().also { activities.getMemoryInfo(it) }
        val storage = StatFs(context.filesDir.path)
        val screen = context.resources.displayMetrics
        fun size(bytes: Long) = Formatter.formatShortFileSize(context, bytes)
        fun version(name: String) = try {
            pm.getPackageInfo(name, 0).versionName ?: "?"
        } catch (_: PackageManager.NameNotFoundException) {
            "not installed"
        }
        append("Report made ${Date()}, app ${Updates.installedVersion(context)}\n")
        append("Phone: ${Build.MANUFACTURER} ${Build.MODEL} (${Build.DEVICE}, ${Build.HARDWARE}, board ${Build.BOARD})")
        if (Build.VERSION.SDK_INT >= 31) append(", SoC ${Build.SOC_MANUFACTURER} ${Build.SOC_MODEL}")
        append("\nAndroid ${Build.VERSION.RELEASE} (SDK ${Build.VERSION.SDK_INT}, patch ${Build.VERSION.SECURITY_PATCH}), ${Build.DISPLAY}\n")
        append("ABIs ${Build.SUPPORTED_ABIS.joinToString()}, page size ${Os.sysconf(OsConstants._SC_PAGESIZE)}, ")
        append("${screen.widthPixels}x${screen.heightPixels} at ${screen.densityDpi} dpi, ${Locale.getDefault()}, ${TimeZone.getDefault().id}\n")
        append("Memory: total ${size(memory.totalMem)}, available ${size(memory.availMem)}, low=${memory.lowMemory}, ")
        append("low-RAM device=${activities.isLowRamDevice}, memory class ${activities.memoryClass}/${activities.largeMemoryClass} MB\n")
        append("Storage: ${size(storage.availableBytes)} free of ${size(storage.totalBytes)}\n")
        val vulkan = pm.systemAvailableFeatures.firstOrNull { it.name == "android.hardware.vulkan.version" }?.version
        append("Graphics: OpenGL ES ${activities.deviceConfigurationInfo.glEsVersion}, Vulkan " +
            (vulkan?.let { "${it shr 22}.${(it shr 12) and 0x3ff}" } ?: "none") + "\n")
        append("Versions: WebView ${WebView.getCurrentWebViewPackage()?.versionName ?: "none"}, Play Services ${version("com.google.android.gms")}, ")
        append("Play Store ${version(MainActivity.PLAY_STORE)}, ARCore ${version("com.google.ar.core")}, Aurora ${version(MainActivity.AURORA)}\n")
        append("Allowed: background running=${context.getSystemService(PowerManager::class.java).isIgnoringBatteryOptimizations(context.packageName)}, ")
        append("installing apps=${pm.canRequestPackageInstalls()}, notifications=${context.getSystemService(NotificationManager::class.java).areNotificationsEnabled()}\n")
        val network = context.getSystemService(ConnectivityManager::class.java).let { it.getNetworkCapabilities(it.activeNetwork) }
        append("Network: " + when {
            network == null -> "none"
            network.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "Wi-Fi"
            network.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "mobile data"
            else -> "other"
        } + "\n")
        val game = installed(context, MainActivity.GAME)
        append("Game: " + (game?.let { "${it.versionName} (${it.longVersionCode}), ${it.splitNames?.size ?: 0} splits, " +
            "${if (playSigned(it)) "Play" else "other"} signature, game libraries ${GameFiles.hasLibraries(it)}, " +
            "${size(File(it.applicationInfo?.sourceDir ?: "").length())} base" } ?: "not installed") + "\n")
        append("Client built for: ${ClientBuildService.builtFor(context)}, built and waiting to install: ${ClientBuildService.resumable(context)}\n")
        append("Setup: signed in to Google ${PlayAccount.signedIn(context)}, extra data downloaded ${PackDownloadService.complete(context)}, ")
        append("map ${Maps.selected(context)?.let { "${Maps.name(context, it)} (${size(it.length())})" } ?: "none"}\n")
        append("Map: ${MapService.status ?: "not started"}\n")
        append("Server: ${ServerService.status}; ports ${ports()}\n")
    }

    /** Whether the server's loopback ports can be bound: when they can't and the server is stopped, another app holds them. */
    private fun ports() = listOf(ServerService.GAME_PORT, ServerService.HTTP_PORT, ServerService.TILE_PORT, ServerService.ADMIN_PORT,
        ServerService.PLACEMENT_PORT, ServerService.LOG_PORT).joinToString { port ->
        "$port " + try {
            ServerSocket(port, 0, InetAddress.getByName("127.0.0.1")).close()
            "free"
        } catch (_: Exception) {
            "in use"
        }
    }

    /** Why this app's processes ended, as Android recorded it: a low-memory kill, a swipe from Recents, a crash. */
    private fun exits(context: Context): String = try {
        context.getSystemService(ActivityManager::class.java).getHistoricalProcessExitReasons(null, 0, 10).joinToString("\n") { e ->
            "${Date(e.timestamp)} ${e.processName} pid ${e.pid}: ${reason(e.reason)}, status ${e.status}, importance ${e.importance}, " +
                "${e.rss / 1024} MB, ${e.description.orEmpty()}"
        }.ifEmpty { "none recorded" }
    } catch (e: Exception) {
        "unavailable: $e"
    }

    private fun reason(code: Int) = when (code) {
        ApplicationExitInfo.REASON_ANR -> "not responding"
        ApplicationExitInfo.REASON_CRASH -> "crash"
        ApplicationExitInfo.REASON_CRASH_NATIVE -> "native crash"
        ApplicationExitInfo.REASON_DEPENDENCY_DIED -> "dependency died"
        ApplicationExitInfo.REASON_EXCESSIVE_RESOURCE_USAGE -> "excessive resource usage"
        ApplicationExitInfo.REASON_EXIT_SELF -> "exited itself"
        ApplicationExitInfo.REASON_INITIALIZATION_FAILURE -> "failed to start"
        ApplicationExitInfo.REASON_LOW_MEMORY -> "killed for low memory"
        ApplicationExitInfo.REASON_OTHER -> "other"
        ApplicationExitInfo.REASON_PERMISSION_CHANGE -> "permission change"
        ApplicationExitInfo.REASON_SIGNALED -> "signaled"
        ApplicationExitInfo.REASON_USER_REQUESTED -> "user requested"
        ApplicationExitInfo.REASON_USER_STOPPED -> "user stopped"
        ApplicationExitInfo.REASON_UNKNOWN -> "unknown"
        else -> "reason $code"
    }

    /** The app's own log lines (an app sees only its own), which hold a crash's stack trace. */
    private fun logcat(): String = try {
        val process = ProcessBuilder("logcat", "-d", "-t", "3000").redirectErrorStream(true).start()
        val text = process.inputStream.bufferedReader().readText()
        process.waitFor(5, TimeUnit.SECONDS)
        text
    } catch (e: Exception) {
        "logcat unavailable: $e"
    }

    fun mask(text: String) = text.replace(EMAIL, "<email>").replace(TOKEN, "<token>").replace(COORDINATES, "<coordinates>")

    /** A run of "TCP read session" lines (the server logs one per read) becomes a count. */
    private fun collapse(text: String): String {
        val out = StringBuilder()
        var left = 0
        for (line in text.lineSequence()) {
            if (line.contains("TCP read session=")) {
                left++
                continue
            }
            if (left > 0) out.append("... $left \"TCP read session\" lines left out\n").also { left = 0 }
            out.append(line).append('\n')
        }
        if (left > 0) out.append("... $left \"TCP read session\" lines left out\n")
        return out.toString()
    }

    private fun tail(file: File, bytes: Int): String {
        RandomAccessFile(file, "r").use { f ->
            val start = maxOf(0L, f.length() - bytes)
            val data = ByteArray((f.length() - start).toInt())
            f.seek(start)
            f.readFully(data)
            return String(data)
        }
    }
}
