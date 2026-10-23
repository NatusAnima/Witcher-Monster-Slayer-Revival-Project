package io.github.natusanima.slayerrevival

import android.app.Activity
import android.app.ActivityManager
import android.app.AlertDialog
import android.graphics.Typeface
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.text.format.Formatter
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ListView
import android.widget.TextView
import android.widget.Toast
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.text.DateFormat
import java.util.Date
import kotlin.concurrent.thread

/**
 * The player's map areas (Update, Delete) and Geofabrik's OpenStreetMap extracts to add one: MapService downloads the chosen
 * extract and builds its map. The server's map services use every area at once.
 */
class RegionActivity : Activity() {
    class Region(val id: String, val name: String, val parent: String, val url: String) {
        override fun toString() = "$name $parent" // what the search matches, word by word
    }

    private lateinit var status: TextView
    private lateinit var search: EditText
    private lateinit var areas: LinearLayout

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val pad = (16 * resources.displayMetrics.density).toInt()
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad, pad, 0)
            fitsSystemWindows = true
        }
        root.addView(TextView(this).apply {
            text = "Map areas"
            textSize = 24f
            typeface = Typeface.create(Typeface.SERIF, Typeface.BOLD)
        })
        root.addView(TextView(this).apply {
            text = "The game uses all your areas at once. Playing across a border? Add the region next door too.\n" +
                "Maps come from OpenStreetMap, in regional extracts made by Geofabrik. Pick the smallest region that covers " +
                "where you play: big regions take long to download and build."
            setPadding(0, pad / 2, 0, pad / 2)
        })
        areas = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(areas)
        root.addView(TextView(this).apply {
            text = "Add an area"
            textSize = 18f
            typeface = Typeface.create(Typeface.SERIF, Typeface.BOLD)
            setPadding(0, pad, 0, 0)
        })
        search = EditText(this).apply {
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

    override fun onResume() {
        super.onResume()
        showAreas()
    }

    /** The areas on this phone, each with Update (when its Geofabrik link is known) and Delete. */
    private fun showAreas() {
        areas.removeAllViews()
        for (index in Maps.all(this)) {
            val row = LinearLayout(this).apply { gravity = Gravity.CENTER_VERTICAL }
            row.addView(TextView(this).apply {
                text = "${Maps.name(this@RegionActivity, index)}\n${Formatter.formatShortFileSize(this@RegionActivity, index.length())}, " +
                    "built ${DateFormat.getDateInstance().format(Date(index.lastModified()))}"
            }, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
            Maps.url(this, index)?.let { url ->
                row.addView(Button(this).apply {
                    text = "Update"
                    setOnClickListener { measure(Region(Maps.id(index), Maps.name(this@RegionActivity, index), "", url)) }
                })
            }
            row.addView(Button(this).apply {
                text = "Delete"
                setOnClickListener { delete(index) }
            })
            areas.addView(row)
        }
    }

    private fun delete(index: File) {
        val name = Maps.name(this, index)
        AlertDialog.Builder(this)
            .setTitle(name)
            .setMessage("Delete the map of $name? Its monsters and places go until you add it again.")
            .setNegativeButton(android.R.string.cancel, null)
            .setPositiveButton("Delete") { _, _ ->
                if (MapService.running) {
                    Toast.makeText(this, "A map is being built. Wait for it, or cancel it first.", Toast.LENGTH_LONG).show()
                } else {
                    Maps.remove(this, index)
                    EventLog.write(this, "map", "deleted the area $name")
                    ServerService.reloadMap(this)
                    showAreas()
                }
            }
            .show()
    }

    /** Geofabrik's regions that have an .osm.pbf extract, ordered as a tree: "Europe", "Europe › Germany", … */
    private fun load(): List<Region> {
        val connection = URL("https://download.geofabrik.de/index-v1-nogeom.json").openConnection() as HttpURLConnection
        connection.connectTimeout = 15_000
        connection.readTimeout = 30_000
        val features = try {
            JSONObject(connection.inputStream.bufferedReader().readText()).getJSONArray("features")
        } finally {
            connection.disconnect()
        }
        val all = (0 until features.length()).map { features.getJSONObject(it).getJSONObject("properties") }
        val names = all.associate { it.getString("id") to readable(it.getString("id"), it.getString("name")) }
        val parents = all.associate { it.getString("id") to it.optString("parent") }
        fun path(id: String): String {
            // the US states hang off North America in the index, with ids like "us/texas": show them under their country
            val country = id.substringBefore('/', "").takeIf { it in names && it != id }
            val parent = (country ?: parents[id])?.takeIf { it in names } ?: return ""
            return listOf(path(parent), names.getValue(parent)).filter { it.isNotEmpty() }.joinToString(" › ")
        }
        return all.filter { it.getJSONObject("urls").has("pbf") }
            // the id names the map's files, so no "/" in it: "us/texas" would be a folder that does not exist
            .map { Region(it.getString("id").replace('/', '-'), names.getValue(it.getString("id")), path(it.getString("id")),
                it.getJSONObject("urls").getString("pbf")) }
            .sortedBy { if (it.parent.isEmpty()) it.name else "${it.parent} › ${it.name}" }
    }

    /**
     * Geofabrik's name for a region as a person reads it. Its index names every US state after its id ("us/new-hampshire"; Georgia
     * alone is "Georgia"), and the Polish and Norwegian regions have an HTML line break in theirs.
     */
    private fun readable(id: String, name: String): String {
        val plain = name.replace(Regex("""\s*<br\s*/?>\s*"""), " ")
        if (plain != id || '/' !in id) return plain
        return id.substringAfterLast('/').split('-').joinToString(" ") { word ->
            when (word) {
                "us" -> "US"
                "of" -> word
                else -> word.replaceFirstChar { it.uppercase() }
            }
        }
    }

    /** Asks Geofabrik for the extract's size, then shows what choosing it takes. */
    private fun measure(region: Region) {
        status.visibility = View.VISIBLE
        status.text = "Asking Geofabrik about ${region.name}…"
        thread(name = "region-size") {
            val answer = try {
                Geofabrik.resolve(region.url).bytes
            } catch (e: Exception) {
                e.message ?: e.javaClass.simpleName
            }
            runOnUiThread {
                if (isFinishing) return@runOnUiThread
                status.visibility = View.GONE
                if (answer is Long && answer > 0) confirm(region, answer) else AlertDialog.Builder(this)
                    .setTitle(region.name)
                    .setMessage("Geofabrik did not give this region's size, so it can't be checked against this phone: " +
                        (if (answer is String) answer else "no size") + "\n\nTry again in a moment, or pick another region.")
                    .setPositiveButton(android.R.string.ok, null)
                    .show()
            }
        }
    }

    private fun confirm(region: Region, bytes: Long) {
        fun size(b: Long) = Formatter.formatShortFileSize(this, b)
        val free = filesDir.usableSpace
        val old = File(Maps.dir(this), "${region.id}-features.sqlite").takeIf { it.isFile } // this area's map, which a build updates
        val others = Maps.all(this) - listOfNotNull(old).toSet()
        val memory = ActivityManager.MemoryInfo().also { getSystemService(ActivityManager::class.java).getMemoryInfo(it) }
        // the node index in RAM takes ~3.7x the extract at its peak: when that does not fit, the slower mode keeps it on disk
        val lowMemory = Maps.peakMemory(bytes) > memory.availMem
        val need = Maps.diskNeeded(bytes, lowMemory, old?.length() ?: 0)
        val enough = free > need
        val mobile = getSystemService(ConnectivityManager::class.java).let {
            it.getNetworkCapabilities(it.activeNetwork)?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) != true
        }
        val message = buildString {
            append("Download: ${size(bytes)} from Geofabrik")
            if (mobile) append(", and you are not on Wi-Fi")
            append("\nMap on this phone: about ${size(bytes * 19 / 10)}\n") // Israel: a 120 MB extract built a 232 MB map
            append("Free space: ${size(free)}; the build needs about ${size(need)}\n")
            append("Time to build: ${Maps.buildTime(bytes)} on a phone (a guess; the build shows the real time once it is going)\n\n")
            append("The map is built on this phone. The screen can go off, but keep this app in the recent apps screen.")
            if (old != null) append(" It updates your map of ${Maps.name(this@RegionActivity, old)}.")
            if (others.isNotEmpty()) append(" The game uses it with your other areas: ${Maps.names(this@RegionActivity, others)}.")
            if (lowMemory) {
                append("\n\nThis region is big for this phone's memory, so the map is built in a slower mode that keeps its working data " +
                    "on disk (about ${size(bytes * 2)} more).")
            }
            if (bytes > 500L shl 20) {
                append("\n\nThis is a big region: it can take hours. A smaller region inside it is better. Tap Smaller regions.")
            }
            if (!enough) append("\n\nThere isn't enough free space for the download and the map.")
        }
        AlertDialog.Builder(this)
            .setTitle(region.name)
            .setMessage(message)
            .setNegativeButton(android.R.string.cancel, null)
            .setNeutralButton("Smaller regions") { _, _ -> search.setText(region.name) } // the list matches parent names: this shows its parts
            .apply { if (enough) setPositiveButton("Download") { _, _ -> start(region, lowMemory) } }
            .show()
    }

    private fun start(region: Region, lowMemory: Boolean) {
        if (MapService.running) {
            Toast.makeText(this, "A map is already being built. Cancel it first (in the notification or the guided setup).",
                Toast.LENGTH_LONG).show()
            return
        }
        MapService.start(this, Maps.Request(region.id, region.name, region.url, lowMemory))
        finish()
    }
}
