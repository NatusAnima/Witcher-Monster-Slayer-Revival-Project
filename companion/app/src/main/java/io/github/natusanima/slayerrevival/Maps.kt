package io.github.natusanima.slayerrevival

import android.content.Context
import java.io.File

/** Map indexes built from OpenStreetMap extracts, kept in files/maps as <region>-features.sqlite. */
object Maps {
    fun dir(context: Context) = File(context.filesDir, "maps")

    private fun prefs(context: Context) = context.getSharedPreferences("maps", Context.MODE_PRIVATE)

    /** The chosen region's index, or else the newest one on the phone. */
    fun selected(context: Context): File? {
        val chosen = prefs(context).getString("index", null)
        chosen?.let { File(dir(context), it) }?.takeIf { it.isFile }?.let { return it }
        return dir(context).listFiles { f -> f.name.endsWith("-features.sqlite") }?.maxByOrNull { it.lastModified() }
    }

    /** The region's name as Geofabrik gives it, or else one made from the file name. */
    fun name(context: Context, index: File): String =
        prefs(context).getString("name", null)?.takeIf { prefs(context).getString("index", null) == index.name }
            ?: index.name.removeSuffix("-features.sqlite").removeSuffix("-latest").replace('-', ' ')
                .replaceFirstChar { it.uppercase() }

    /** Makes [index] the map the server loads, replacing the other regions' indexes. */
    fun select(context: Context, index: File, name: String) {
        prefs(context).edit().putString("index", index.name).putString("name", name).apply()
        dir(context).listFiles { f -> f.name.endsWith("-features.sqlite") && f.name != index.name }?.forEach { it.delete() }
    }
}
