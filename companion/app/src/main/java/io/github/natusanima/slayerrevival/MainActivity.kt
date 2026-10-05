package io.github.natusanima.slayerrevival

import android.Manifest
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageInstaller
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.format.Formatter
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.LinearLayout.LayoutParams
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import java.io.File
import java.io.RandomAccessFile
import java.security.MessageDigest

class MainActivity : Activity() {
    companion object {
        const val GAME = "com.spokko.witchermonsterslayer"
        const val GAME_VERSION = 300085L
        const val AURORA = "com.aurora.store"
        const val PLAY_STORE = "com.android.vending"
        const val PLAY = "io.github.natusanima.slayerrevival.PLAY"
        const val INSTALL = "io.github.natusanima.slayerrevival.INSTALL"
        const val SITE = "https://github.com/${Updates.REPO}"
        const val GUIDE = "$SITE#phone-only-play-the-companion-app"
        const val AURORA_SITE = "https://gitlab.com/AuroraOSS/AuroraStore"
        /** SHA-256 of the certificate Google Play signs the game with: Aurora's copy, before the playable client. */
        const val PLAY_CERT = "35bb00ec82bd877bdcf816cdecba2c99566cf307015ca876768606ce258b3785"

        // The setup steps, one short line each. The commands for the PC part are in the guide (README).
        private val DOWNLOAD_STEPS = listOf(
            "Tap Open in Aurora below. If it asks how to sign in, Anonymous is enough.",
            "Tap the three dots at the top right, then Manual download.",
            "Enter the version code 300085. Not 1.1.116.",
            "Download and install it.",
        )
        private val UPDATE_STEPS = listOf(
            "Tap Open in Play Store below. If Play can't find the game, skip this step: nothing can update it.",
            "Tap the three dots at the top right of the game's page.",
            "Untick Enable auto update. Never tap Update.",
        )
        private val CLIENT_STEPS = listOf(
            "Pull the game's files from the phone.",
            "Reinstall them with Google Play as the installer. Aurora doesn't do this, and without it the game never " +
                "downloads its extra 1.3\u00A0GB.",
            "Open the game and accept the 1.3\u00A0GB download. Don't tap Update in the Play Store.",
            "Back up the downloaded data from the phone and unpack it on the PC.",
            "Build the playable client and replace the Play copy of the game with it.",
            "Copy the game hook to the phone.",
        )

        private const val SURFACE = 0xFF1E1E24.toInt()
        private const val TEXT = 0xFFEDEAE4.toInt()
        private const val MUTED = 0xFF9E9BA5.toInt()
        private const val GOLD = 0xFFD9A441.toInt()
        private const val GREEN = 0xFF72C472.toInt()
        private const val RED = 0xFFE8695E.toInt()
        private val LOGS = listOf("server" to "Server", "tiles" to "Tiles", "placement" to "Placement", "map-build" to "Map build")
    }

    private var playing = false
    private var logName = "server"
    private val handler = Handler(Looper.getMainLooper())
    private val refresh = object : Runnable {
        override fun run() {
            render()
            handler.postDelayed(this, 1000)
        }
    }

    private lateinit var updateCard: LinearLayout
    private lateinit var updateText: TextView
    private lateinit var updateButton: Button
    private lateinit var serverDot: TextView
    private lateinit var serverText: TextView
    private lateinit var mapText: TextView
    private lateinit var toggle: Button
    private lateinit var dashboard: Button
    private lateinit var aurora: Step
    private lateinit var game: Step
    private lateinit var client: Step
    private lateinit var region: Step
    private lateinit var logTabs: List<Button>
    private lateinit var log: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 0)
        val page = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(px(16), px(20), px(16), px(16))
        }
        // The app's name, "Witcher Monster Slayer - Revival", set as two lines: it doesn't fit on one.
        page.addView(text(26f).apply {
            text = "Witcher Monster Slayer"
            typeface = Typeface.create(Typeface.SERIF, Typeface.BOLD)
        })
        page.addView(text(26f, GOLD).apply {
            text = "Revival"
            typeface = Typeface.create(Typeface.SERIF, Typeface.BOLD)
        })
        page.addView(text(14f, MUTED).apply {
            text = "Your own game server for version 1.1.116, running on this phone."
            setPadding(0, px(6), 0, px(16))
        })

        updateCard = card(page, "Update")
        updateText = text(15f).also { updateCard.addView(it) }
        updateButton = button("Update", primary = true) { Updates.install(this) }.also { updateCard.addView(it) }

        val play = card(page, "Play")
        val status = LinearLayout(this).apply { gravity = Gravity.CENTER_VERTICAL }
        serverDot = text(18f).apply {
            text = "●"
            setPadding(0, 0, px(8), 0)
        }
        serverText = text(16f, bold = true)
        status.addView(serverDot)
        status.addView(serverText, LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f))
        play.addView(status)
        mapText = text(14f, MUTED).also { play.addView(it) }
        play.addView(button("Play", primary = true) { play() },
            LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT).apply { topMargin = px(12) })
        val buttons = LinearLayout(this)
        toggle = button("Start server") {
            if (ServerService.status == "Stopped") startForegroundService(Intent(this, ServerService::class.java))
            else startService(Intent(this, ServerService::class.java).setAction(ServerService.STOP))
        }
        dashboard = button("Dashboard") { startActivity(Intent(this, DashboardActivity::class.java)) }
        buttons.addView(toggle, LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f))
        buttons.addView(dashboard, LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f))
        play.addView(buttons)

        val setup = card(page, "Setup")
        aurora = Step(setup, 1, "Aurora Store")
        game = Step(setup, 2, "The game, version 1.1.116")
        client = Step(setup, 3, "The playable client")
        region = Step(setup, 4, "Your map region")

        val logs = card(page, "Logs")
        val tabs = LinearLayout(this)
        logTabs = LOGS.map { (name, title) -> button(title) { logName = name; render() }.also { tabs.addView(it) } }
        logs.addView(HorizontalScrollView(this).apply { addView(tabs) })
        log = text(11f, MUTED).apply { typeface = Typeface.MONOSPACE }
        logs.addView(log)

        page.addView(text(12f, MUTED).apply {
            text = "Map data © OpenStreetMap contributors"
            gravity = Gravity.CENTER_HORIZONTAL
        })
        page.addView(text(12f, MUTED).apply {
            text = "Not affiliated with CD PROJEKT RED or Spokko."
            gravity = Gravity.CENTER_HORIZONTAL
        })
        val version = packageManager.getPackageInfo(packageName, 0).versionName
        page.addView(button("Version $version · Source code and credits") { open(SITE) }.apply { textSize = 12f },
            LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT).apply { gravity = Gravity.CENTER_HORIZONTAL })

        setContentView(ScrollView(this).apply {
            fitsSystemWindows = true
            addView(page)
        })
        Updates.check(this)
        if (savedInstanceState == null) handle(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handle(intent)
    }

    private fun handle(intent: Intent?) {
        when (intent?.action) {
            PLAY -> play()
            INSTALL -> when (intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)) {
                PackageInstaller.STATUS_PENDING_USER_ACTION ->
                    @Suppress("DEPRECATION") intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)?.let(::startActivity)
                PackageInstaller.STATUS_SUCCESS -> Unit
                PackageInstaller.STATUS_FAILURE_ABORTED -> Updates.finished("The update was cancelled.")
                else -> Updates.finished("The update failed: ${intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE)}")
            }
        }
    }

    /** Starts the server, then opens the game once it answers. */
    private fun play() {
        if (packageManager.getLaunchIntentForPackage(GAME) == null) {
            Toast.makeText(this, "Install the game first: see Setup", Toast.LENGTH_LONG).show()
            return
        }
        playing = true
        startForegroundService(Intent(this, ServerService::class.java))
    }

    override fun onResume() {
        super.onResume()
        handler.post(refresh)
    }

    override fun onPause() {
        handler.removeCallbacks(refresh)
        super.onPause()
    }

    private fun render() {
        val server = ServerService.status
        serverText.text = when (server) {
            "Running" -> "Server running"
            "Stopped" -> "Server stopped"
            "Preparing" -> "Server starting…"
            else -> server
        }
        serverDot.setTextColor(when {
            server == "Running" -> GREEN
            server == "Stopped" -> MUTED
            server == "Preparing" || server.startsWith("Running") -> GOLD
            else -> RED
        })
        toggle.text = if (server == "Stopped") "Start server" else "Stop server"
        dashboard.isEnabled = server.startsWith("Running")
        val index = Maps.selected(this)
        mapText.text = "Map: " + (index?.let { Maps.name(this, it) } ?: "none yet, choose your region below")
        if (playing && server == "Running") {
            playing = false
            packageManager.getLaunchIntentForPackage(GAME)?.let(::startActivity)
        }

        val release = Updates.latest
        updateCard.visibility = if (release == null) View.GONE else View.VISIBLE
        if (release != null) {
            updateText.text = "Version ${release.version} is available. Updating keeps your progress." +
                (Updates.status?.let { "\n$it" } ?: "")
            updateButton.isEnabled = !Updates.busy
        }

        val why = "Aurora downloads apps from Google Play, including older versions, which the Play Store can't."
        if (installed(AURORA) != null) aurora.show(true, "Installed. $why")
        else aurora.show(false, "$why Get it from its official page.", "Get Aurora Store") { open(AURORA_SITE) }

        val installed = installed(GAME)
        val ready = installed?.longVersionCode == GAME_VERSION
        val fromPlay = installed != null && playSigned(installed) // Play can still update it, until the playable client replaces it
        when {
            installed == null -> game.show(false, "Download this exact version with Aurora:", "Open in Aurora", items = DOWNLOAD_STEPS) { openInAurora() }
            !ready -> game.show(false, "Version ${installed.versionName} is installed, but this needs 1.1.116 (300085). " +
                "Uninstall it, then download the right version with Aurora:", "Open in Aurora", items = DOWNLOAD_STEPS) { openInAurora() }
            fromPlay -> game.show(true, "1.1.116 (300085) is installed. Now stop Google Play from updating it to 1.3.102:",
                "Open in Play Store", items = UPDATE_STEPS) { openInPlay() }
            else -> game.show(true, "1.1.116 (300085) is installed.")
        }
        when {
            installed == null || !ready || fromPlay -> client.show(false, "This part needs a PC with USB debugging, once, " +
                "after step 2. The guide has every command:", "Open the guide", items = CLIENT_STEPS) { open(GUIDE) }
            else -> client.show(true, "Installed: the game connects to this app.")
        }

        val outcome = MapService.status?.let { "\n\n$it" } ?: ""
        val choose = { startActivity(Intent(this, RegionActivity::class.java)) }
        when {
            MapService.running -> region.show(false, MapService.status ?: "Starting", "Cancel", MapService.progress) {
                startService(Intent(this, MapService::class.java).setAction(MapService.CANCEL))
            }
            index != null -> region.show(true, "${Maps.name(this, index)}, ${Formatter.formatShortFileSize(this, index.length())} " +
                "on this phone.$outcome", "Change region", onClick = choose)
            else -> region.show(false, "The map comes from OpenStreetMap. Pick the region you play in: the app downloads " +
                "it from Geofabrik and builds the map on this phone.$outcome", "Choose region", onClick = choose)
        }

        logTabs.forEachIndexed { i, tab -> tab.setTextColor(if (LOGS[i].first == logName) GOLD else MUTED) }
        log.text = tail(File(filesDir, "logs/$logName.log"))
    }

    private fun installed(name: String): PackageInfo? = try {
        packageManager.getPackageInfo(name, PackageManager.GET_SIGNING_CERTIFICATES)
    } catch (_: PackageManager.NameNotFoundException) {
        null
    }

    private fun playSigned(info: PackageInfo) = info.signingInfo?.apkContentsSigners.orEmpty().any { signer ->
        MessageDigest.getInstance("SHA-256").digest(signer.toByteArray()).joinToString("") { "%02x".format(it) } == PLAY_CERT
    }

    private fun openInAurora() = try {
        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=$GAME")).setPackage(AURORA))
    } catch (_: ActivityNotFoundException) {
        open(AURORA_SITE)
    }

    private fun openInPlay() = try {
        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=$GAME")).setPackage(PLAY_STORE))
    } catch (_: ActivityNotFoundException) {
        Toast.makeText(this, "Google Play isn't installed on this phone.", Toast.LENGTH_LONG).show()
    }

    private fun open(url: String) = try {
        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
    } catch (_: ActivityNotFoundException) {
    }

    /** The last lines of a log, read from its end: the server's grows large over a long session. */
    private fun tail(file: File): String {
        if (!file.isFile) return "No log yet."
        RandomAccessFile(file, "r").use { f ->
            val start = maxOf(0L, f.length() - 16_384)
            val bytes = ByteArray((f.length() - start).toInt())
            f.seek(start)
            f.readFully(bytes)
            return String(bytes).lines().drop(if (start > 0) 1 else 0).takeLast(60).joinToString("\n")
        }
    }

    private fun px(dp: Int) = (dp * resources.displayMetrics.density).toInt()

    private fun text(size: Float, color: Int = TEXT, bold: Boolean = false) = TextView(this).apply {
        textSize = size
        setTextColor(color)
        if (bold) typeface = Typeface.DEFAULT_BOLD
    }

    private fun button(label: String, primary: Boolean = false, action: () -> Unit) = Button(this, null, 0,
        if (primary) android.R.style.Widget_Material_Button_Colored else android.R.style.Widget_Material_Button_Borderless_Colored
    ).apply {
        text = label
        setOnClickListener { action() }
    }

    private fun card(page: LinearLayout, title: String) = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(px(16), px(14), px(16), px(12))
        background = GradientDrawable().apply {
            setColor(SURFACE)
            cornerRadius = px(16).toFloat()
        }
        addView(text(12f, GOLD, bold = true).apply {
            text = title.uppercase()
            letterSpacing = 0.1f
        })
        page.addView(this, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT).apply { bottomMargin = px(12) })
    }

    /** One setup step: a numbered mark (a tick once done), what to do, any sub-steps, and the button that does it. */
    private inner class Step(parent: LinearLayout, private val number: Int, title: String) {
        private val mark = text(13f, bold = true).apply { gravity = Gravity.CENTER }
        private val body = text(14f, MUTED)
        private val list = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.VERTICAL }
        private var listed = emptyList<String>()
        private val bar = ProgressBar(this@MainActivity, null, 0, android.R.style.Widget_Material_ProgressBar_Horizontal)
            .apply { max = 100 }
        private val action = button("") {}.apply { setPadding(0, paddingTop, paddingRight, paddingBottom) }

        init {
            val column = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.VERTICAL }
            column.addView(text(16f, bold = true).apply { text = title })
            column.addView(body)
            column.addView(list)
            column.addView(bar)
            column.addView(action, LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT))
            val row = LinearLayout(this@MainActivity).apply { setPadding(0, px(12), 0, 0) }
            row.addView(mark, LayoutParams(px(24), px(24)).apply { marginEnd = px(12) })
            row.addView(column, LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f))
            parent.addView(row)
        }

        fun show(done: Boolean, message: String, label: String? = null, progress: Int? = null,
                 items: List<String> = emptyList(), onClick: () -> Unit = {}) {
            if (items != listed) { // the screen refreshes every second: rebuild the rows only when they change
                listed = items
                list.removeAllViews()
                items.forEachIndexed { i, item ->
                    val row = LinearLayout(this@MainActivity).apply { setPadding(0, px(6), 0, 0) }
                    row.addView(text(14f, GOLD, bold = true).apply { text = "${i + 1}." }, LayoutParams(px(24), LayoutParams.WRAP_CONTENT))
                    row.addView(text(14f).apply { text = item }, LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f))
                    list.addView(row)
                }
            }
            mark.text = if (done) "✓" else "$number"
            mark.setTextColor(if (done) SURFACE else GOLD)
            mark.background = GradientDrawable().apply {
                shape = GradientDrawable.OVAL
                if (done) setColor(GREEN) else setStroke(px(1).coerceAtLeast(2), GOLD)
            }
            body.text = message
            bar.visibility = if (progress == null) View.GONE else View.VISIBLE
            if (progress != null) {
                bar.isIndeterminate = progress < 0
                bar.progress = progress.coerceAtLeast(0)
            }
            action.visibility = if (label == null) View.GONE else View.VISIBLE
            action.text = label
            action.setOnClickListener { onClick() }
        }
    }
}
