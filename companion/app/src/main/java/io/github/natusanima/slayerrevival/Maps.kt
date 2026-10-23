package io.github.natusanima.slayerrevival

import android.content.Context
import java.io.File

/** Map indexes built from OpenStreetMap extracts, kept in files/maps as <region>-features.sqlite: the player's map areas. */
object Maps {
    fun dir(context: Context) = File(context.filesDir, "maps")

    private fun prefs(context: Context) = context.getSharedPreferences("maps", Context.MODE_PRIVATE)

    /** The player's map areas, oldest first: the server's map services load them all, and neighbours answer as one map. */
    fun all(context: Context): List<File> =
        dir(context).listFiles { f -> f.name.endsWith("-features.sqlite") }?.sortedBy { it.lastModified() } ?: emptyList()

    /** The area's region id: its files are named after it. */
    fun id(index: File) = index.name.removeSuffix("-features.sqlite")

    /** The region's name as Geofabrik gives it, or else one made from the file name. */
    fun name(context: Context, index: File): String =
        prefs(context).getString("name:${index.name}", null)
            // a map from before the areas: the one region's name was kept beside its file name
            ?: prefs(context).getString("name", null)?.takeIf { prefs(context).getString("index", null) == index.name }
            ?: id(index).removeSuffix("-latest").replace('-', ' ').replaceFirstChar { it.uppercase() }

    /** The area's Geofabrik link, for Update; null for a map from before the areas (adding its region again updates it). */
    fun url(context: Context, index: File): String? = prefs(context).getString("url:${index.name}", null)

    /** "Poland, Lithuania" for [indexes]. */
    fun names(context: Context, indexes: List<File>) = indexes.joinToString(", ") { name(context, it) }

    /** Keeps a built map among the areas, under its region's name and link. */
    fun add(context: Context, index: File, name: String, url: String) =
        prefs(context).edit().putString("name:${index.name}", name).putString("url:${index.name}", url).apply()

    /** Deletes an area's map. */
    fun remove(context: Context, index: File) {
        index.delete()
        prefs(context).edit().remove("name:${index.name}").remove("url:${index.name}").apply()
    }

    /** What the player asked for, kept until its map is built so that Try again can carry on with it. */
    data class Request(val id: String, val name: String, val url: String, val lowMemory: Boolean)

    fun request(context: Context): Request? = prefs(context).let { p ->
        p.getString("request_id", null)?.let {
            // an id from an older build can be "us/texas": the id names the map's files, so it carries no "/"
            Request(it.replace('/', '-'), p.getString("request_name", it)!!, p.getString("request_url", "")!!, p.getBoolean("request_low", false))
        }
    }

    fun setRequest(context: Context, request: Request?) {
        prefs(context).edit().apply {
            if (request == null) {
                remove("request_id").remove("request_name").remove("request_url").remove("request_low")
            } else {
                putString("request_id", request.id).putString("request_name", request.name)
                    .putString("request_url", request.url).putBoolean("request_low", request.lowMemory)
            }
        }.apply()
    }

    /** How the last build ended, in words for the player; null if it worked, was cancelled or never ran. */
    fun failure(context: Context): String? = prefs(context).getString("failure", null)

    fun setFailure(context: Context, message: String?) = prefs(context).edit().putString("failure", message).apply()

    /** Removes what a build leaves behind (partial downloads, half-made indexes), except the download [request] may still resume. */
    fun sweep(context: Context) {
        val keep = request(context)?.id
        dir(context).listFiles()?.filter { f ->
            val n = f.name
            f.isDirectory || // an older build put a US state in maps/us/, where nothing looks for it: its map was never used
                (n.contains(".osm.pbf") && (keep == null || !n.startsWith("$keep."))) ||
                n.endsWith(".sqlite.new") || n.endsWith(".sqlite.new.partial") || n.endsWith(".sqlite.new.nodes")
        }?.forEach { it.deleteRecursively() }
    }

    // Sizes and times for the region dialog. The memory and time figures are rules of thumb: the node index takes about 3.7 times
    // the extract at its peak, and a phone builds in an estimated 3 to 6 seconds per MB (measured on a PC: 0.6). See the docs.
    private const val MB = 1_048_576L

    /** Free space a build needs beyond what is already on disk: the download, the index (~2x), a spare, and the area's old index. */
    fun diskNeeded(bytes: Long, lowMemory: Boolean, oldIndex: Long) =
        bytes * 7 / 2 + oldIndex + 200 * MB + (if (lowMemory) bytes * 2 else 0)

    /** The memory the build can need at its peak when the node index is kept in RAM. */
    fun peakMemory(bytes: Long) = bytes * 37 / 10 + 300 * MB

    /** "about 6 to 12 min" for building [bytes] of extract. */
    fun buildTime(bytes: Long): String {
        val low = (bytes / MB * 3 / 60).toInt().coerceAtLeast(1)
        val high = (bytes / MB * 6 / 60).toInt().coerceAtLeast(low + 1)
        return if (high < 90) "about $low to $high min" else "about ${(low + 30) / 60} to ${(high + 30) / 60} h"
    }

    /** "about 12 min" for [seconds]. */
    fun duration(seconds: Long): String = when {
        seconds < 90 -> "about a minute"
        seconds < 3600 -> "about ${(seconds + 30) / 60} min"
        else -> "about ${seconds / 3600} h" + ((seconds % 3600 + 30) / 60).let { if (it > 0) " $it min" else "" }
    }
}
