package io.github.natusanima.slayerrevival

import android.content.Context
import java.io.File

/** Map indexes built from OpenStreetMap extracts, kept in files/maps as <region>-features.sqlite. */
object Maps {
    fun dir(context: Context) = File(context.filesDir, "maps")

    /** The chosen region's index, or else the newest one on the phone. */
    fun selected(context: Context): File? {
        val chosen = context.getSharedPreferences("maps", Context.MODE_PRIVATE).getString("index", null)
        chosen?.let { File(dir(context), it) }?.takeIf { it.isFile }?.let { return it }
        return dir(context).listFiles { f -> f.name.endsWith("-features.sqlite") }?.maxByOrNull { it.lastModified() }
    }
}
