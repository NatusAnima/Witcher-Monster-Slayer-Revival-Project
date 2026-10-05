package io.github.natusanima.slayerrevival

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.graphics.Typeface
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.text.format.Formatter
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ListView
import android.widget.TextView
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/** Lists Geofabrik's OpenStreetMap extracts; MapService downloads the chosen one and builds its map. */
class RegionActivity : Activity() {
    class Region(val id: String, val name: String, val parent: String, val url: String) {
        override fun toString() = "$name $parent" // what the search matches, word by word
    }

    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val pad = (16 * resources.displayMetrics.density).toInt()
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad, pad, 0)
            fitsSystemWindows = true
        }
        root.addView(TextView(this).apply {
            text = "Choose your region"
            textSize = 24f
            typeface = Typeface.create(Typeface.SERIF, Typeface.BOLD)
        })
        root.addView(TextView(this).apply {
            text = "The map comes from OpenStreetMap, in regional extracts made by Geofabrik. Pick the smallest " +
                "region that covers where you play: big regions take long to download and build."
            setPadding(0, pad / 2, 0, pad / 2)
        })
        val search = EditText(this).apply {
            hint = "Search, for example Poland or United Kingdom"
            isSingleLine = true
        }
        root.addView(search)
        status = TextView(this).apply {
            text = "Loading the regions…"
            setPadding(0, pad, 0, 0)
        }
        root.addView(status)
        val list = ListView(this)
        root.addView(list, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        setContentView(root)

        thread(name = "regions") {
            val regions = try {
                load()
            } catch (e: Exception) {
                runOnUiThread { status.text = "Couldn't load the regions: ${e.message}" }
                return@thread
            }
            runOnUiThread {
                status.visibility = View.GONE
                val adapter = object : ArrayAdapter<Region>(this, android.R.layout.simple_list_item_2, android.R.id.text1, regions) {
                    override fun getView(position: Int, convertView: View?, parent: ViewGroup): View =
                        super.getView(position, convertView, parent).apply {
                            val region = getItem(position)!!
                            findViewById<TextView>(android.R.id.text1).text = region.name
                            findViewById<TextView>(android.R.id.text2).text = region.parent
                        }
                }
                list.adapter = adapter
                list.setOnItemClickListener { _, _, position, _ -> measure(adapter.getItem(position)!!) }
                search.addTextChangedListener(object : TextWatcher {
                    override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                    override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
                    override fun afterTextChanged(s: Editable?) = adapter.filter.filter(s)
                })
            }
        }
    }

    /** Geofabrik's regions that have an .osm.pbf extract, ordered as a tree: "Europe", "Europe › Germany", … */
    private fun load(): List<Region> {
        val features = JSONObject(URL("https://download.geofabrik.de/index-v1-nogeom.json").readText()).getJSONArray("features")
        val all = (0 until features.length()).map { features.getJSONObject(it).getJSONObject("properties") }
        val names = all.associate { it.getString("id") to it.getString("name") }
        val parents = all.associate { it.getString("id") to it.optString("parent") }
        fun path(id: String): String {
            val parent = parents[id]?.takeIf { it in names } ?: return ""
            return listOf(path(parent), names.getValue(parent)).filter { it.isNotEmpty() }.joinToString(" › ")
        }
        return all.filter { it.getJSONObject("urls").has("pbf") }
            .map { Region(it.getString("id"), it.getString("name"), path(it.getString("id")), it.getJSONObject("urls").getString("pbf")) }
            .sortedBy { if (it.parent.isEmpty()) it.name else "${it.parent} › ${it.name}" }
    }

    /** Asks Geofabrik for the extract's size, then shows what choosing it takes. */
    private fun measure(region: Region) {
        thread(name = "region-size") {
            val bytes = try {
                val connection = URL(region.url).openConnection() as HttpURLConnection
                connection.requestMethod = "HEAD"
                connection.connectTimeout = 15_000
                connection.readTimeout = 15_000
                connection.contentLengthLong.also { connection.disconnect() }
            } catch (_: Exception) {
                -1L
            }
            runOnUiThread { if (!isFinishing) confirm(region, bytes) }
        }
    }

    private fun confirm(region: Region, bytes: Long) {
        fun size(b: Long) = Formatter.formatShortFileSize(this, b)
        val free = filesDir.usableSpace
        val enough = bytes < 0 || free > bytes * 3 // the extract, the map built from it, and room to spare
        val current = Maps.selected(this)?.let { Maps.name(this, it) }
        val message = buildString {
            if (bytes >= 0) {
                append("Download: ${size(bytes)} from Geofabrik\n")
                append("Map on this phone: about ${size(bytes * 19 / 10)}\n") // Israel: a 120 MB extract built a 232 MB map
            } else {
                append("Geofabrik didn't say how big this region is.\n")
            }
            append("Free space: ${size(free)}\n\n")
            append("The map is built on this phone, which takes a few minutes.")
            if (current != null) append(" It replaces your current map, $current.")
            if (bytes > 1_000_000_000) {
                append("\n\nThis is a big region: building it can take an hour and may run out of memory. A smaller sub-region is better.")
            }
            if (!enough) append("\n\nThere isn't enough free space for the download and the map.")
        }
        AlertDialog.Builder(this)
            .setTitle(region.name)
            .setMessage(message)
            .setNegativeButton(android.R.string.cancel, null)
            .apply { if (enough) setPositiveButton("Download") { _, _ -> start(region) } }
            .show()
    }

    private fun start(region: Region) {
        startForegroundService(Intent(this, MapService::class.java)
            .putExtra("id", region.id).putExtra("name", region.name).putExtra("url", region.url))
        finish()
    }
}
