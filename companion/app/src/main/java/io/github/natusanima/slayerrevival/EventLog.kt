package io.github.natusanima.slayerrevival

import android.app.ActivityManager
import android.content.Context
import android.os.PowerManager
import java.io.File
import java.io.FileInputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * One chronological log of what the app did (setup steps, downloads, builds, the server), kept for bug reports:
 * every service writes its status changes here, so a report shows the order of events, not just each part's own log.
 */
object EventLog {
    private const val LIMIT = 1_000_000L
    private val time = ThreadLocal.withInitial { SimpleDateFormat("MM-dd HH:mm:ss.SSS", Locale.US) }

    @Synchronized
    fun write(context: Context, tag: String, line: String) {
        try {
            val file = File(context.applicationContext.filesDir, "logs/events.log")
            file.parentFile?.mkdirs()
            if (file.length() > LIMIT) file.renameTo(File(file.parentFile, "events.prev.log"))
            file.appendText("${time.get()!!.format(Date())} $tag $line\n")
        } catch (_: Exception) {
            // a log must never take the app down
        }
    }

    /** One line of what the phone is doing, for the timeline: free memory, the server's processes and their memory, heat. */
    fun sample(context: Context) {
        try {
            val manager = context.getSystemService(ActivityManager::class.java)
            val info = ActivityManager.MemoryInfo().also { manager.getMemoryInfo(it) }
            val thermal = context.getSystemService(PowerManager::class.java).currentThermalStatus
            write(context, "phone", "memory available ${mb(kb("/proc/meminfo", "MemAvailable"))}, low=${info.lowMemory}, " +
                "threshold ${mb(info.threshold / 1024)}; ${children(context)}; thermal $thermal")
        } catch (_: Exception) {
        }
    }

    /** The server's processes as "name RSS (anonymous part)": found by their command line, which only this app's own are readable. */
    private fun children(context: Context): String {
        val libDir = context.applicationInfo.nativeLibraryDir
        val found = File("/proc").listFiles().orEmpty().mapNotNull { dir ->
            if (dir.name.toIntOrNull() == null) return@mapNotNull null
            val args = try {
                FileInputStream(File(dir, "cmdline")).use { String(it.readBytes()) }.split('\u0000')
            } catch (_: Exception) {
                return@mapNotNull null
            }
            if (!args[0].startsWith(libDir)) return@mapNotNull null
            val name = (if (args.size > 1 && args[1].endsWith(".py")) args[1] else args[0]).substringAfterLast('/')
            "$name ${mb(kb("${dir.path}/status", "VmRSS"))} (anon ${mb(kb("${dir.path}/status", "RssAnon"))})"
        }
        return if (found.isEmpty()) "no server processes" else found.joinToString(", ")
    }

    /** A "Name:   123 kB" line of a /proc file, in kB; 0 if it is missing. */
    private fun kb(path: String, key: String): Long = try {
        FileInputStream(path).use { String(it.readBytes()) }.lineSequence().firstOrNull { it.startsWith("$key:") }
            ?.filter { it.isDigit() }?.toLongOrNull() ?: 0
    } catch (_: Exception) {
        0
    }

    private fun mb(kb: Long) = "${kb / 1024} MB"
}
