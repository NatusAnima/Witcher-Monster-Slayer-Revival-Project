package io.github.natusanima.slayerrevival

import android.Manifest
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageInstaller
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.LinearLayout.LayoutParams
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import java.io.File
import java.io.RandomAccessFile

class MainActivity : Activity() {
    companion object {
        const val GAME = "com.spokko.witchermonsterslayer"
        const val GAME_VERSION = 300085L
        const val AURORA = "com.aurora.store"
        const val PLAY_STORE = "com.android.vending"
        const val PLAY = "io.github.natusanima.slayerrevival.PLAY"
        const val INSTALL = "io.github.natusanima.slayerrevival.INSTALL"
        const val SITE = "https://github.com/${Updates.REPO}"
        const val DISCORD = "https://discord.gg/dEJQfecqnU"
        const val AURORA_SITE = "https://gitlab.com/AuroraOSS/AuroraStore"
        /** SHA-256 of the certificate Google Play signs the game with: Aurora's copy, before the playable client. */
        const val PLAY_CERT = "35bb00ec82bd877bdcf816cdecba2c99566cf307015ca876768606ce258b3785"

        private const val SURFACE = 0xFF1E1E24.toInt()
        private const val TEXT = 0xFFEDEAE4.toInt()
        private const val MUTED = 0xFF9E9BA5.toInt()
        private const val GOLD = 0xFFD9A441.toInt()
        private const val GREEN = 0xFF72C472.toInt()
        private const val RED = 0xFFE8695E.toInt()
        private val LOGS = listOf("events" to "Events", "game" to "Game", "server" to "Server", "tiles" to "Tiles",
            "placement" to "Placement", "map-build" to "Map build")
    }

    private var playing = false
    private var ours = false // the installed game is the client this app built, so it can be updated in place
    private var updateAction = {}
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
        updateButton = button("Update", primary = true) { updateAction() }.also { updateCard.addView(it) }

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
        setup.addView(text(14f, MUTED).apply {
            text = "Every step from installing the game to choosing your map, one at a time."
            setPadding(0, px(6), 0, px(6))
        })
        setup.addView(button("Open the guided setup", primary = true) { startActivity(Intent(this, SetupActivity::class.java)) })

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
        page.addView(button("Send a report") { DebugInfo.share(this) }.apply { textSize = 12f },
            LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT).apply { gravity = Gravity.CENTER_HORIZONTAL })
        page.addView(button("Report on GitHub (public)") { DebugInfo.issue(this) }.apply { textSize = 12f },
            LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT).apply { gravity = Gravity.CENTER_HORIZONTAL })
        page.addView(button("Join the Discord community") { open(DISCORD) }.apply { textSize = 12f },
            LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT).apply { gravity = Gravity.CENTER_HORIZONTAL })
        val version = packageManager.getPackageInfo(packageName, 0).versionName
        page.addView(button("Version $version · Source code and credits") { open(SITE) }.apply { textSize = 12f },
            LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT).apply { gravity = Gravity.CENTER_HORIZONTAL })

        setContentView(ScrollView(this).apply {
            fitsSystemWindows = true
            addView(page)
        })
        Updates.check(this)
        if (!MapService.running) Maps.sweep(this) // downloads and half-made maps that nothing will resume
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
        val game = DebugInfo.installed(this, GAME)
        if (game == null || packageManager.getLaunchIntentForPackage(GAME) == null) {
            Toast.makeText(this, "Install the game first: see Setup", Toast.LENGTH_LONG).show()
            return
        }
        if (DebugInfo.playSigned(game)) { // the original from Google Play talks to servers that are gone
            Toast.makeText(this, "This is the original game from Google Play, which cannot reach this server. " +
                "Finish step 5 of the guided setup to install the playable client.", Toast.LENGTH_LONG).show()
            EventLog.write(this, "play", "refused: the installed game is the Google Play copy")
            return
        }
        EventLog.write(this, "play", "tapped, server ${ServerService.status}")
        playing = true
        startForegroundService(Intent(this, ServerService::class.java))
    }

    override fun onResume() {
        super.onResume()
        ours = ClientBuildService.signedByUs(this) == true // asks the keystore: once here, not on every refresh
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
        val unfinished = Maps.request(this) // a map was asked for and did not get built
        mapText.text = "Map: " + when {
            MapService.running -> MapService.status ?: "building"
            unfinished != null -> "the map of ${unfinished.name} did not finish: open the guided setup and tap Try again" +
                (index?.let { " (the earlier map, ${Maps.name(this, it)}, still works)" } ?: "")
            index != null -> Maps.name(this, index)
            else -> "none yet, choose it in the guided setup"
        }
        if (playing && server == "Running") {
            playing = false
            EventLog.write(this, "play", "server is running: opening the game")
            packageManager.getLaunchIntentForPackage(GAME)?.let(::startActivity)
        }

        val release = Updates.latest
        val gameStale = ours && ClientBuildService.builtForOther(this, Updates.installedVersion(this))
        updateCard.visibility = if (release == null && !gameStale) View.GONE else View.VISIBLE
        if (release != null) {
            updateText.text = "Version ${release.version} is available. " +
                (if (release.game) "It also updates the game: when it is installed, tap Update the game here. "
                else if (ours) "It leaves your game as it is. " else "") +
                "Updating keeps your progress." + (Updates.status?.let { "\n$it" } ?: "")
            updateButton.text = "Update"
            updateButton.isEnabled = !Updates.busy
            updateAction = { Updates.install(this) }
        } else if (gameStale) {
            updateText.text = "The game needs updating to match this version of the app. It takes a few minutes and keeps your " +
                "progress. Needs about 6 GB free while it runs." + (ClientBuildService.status?.let { "\n$it" } ?: "")
            val waiting = ClientBuildService.pending != null // Android is waiting for a tap on its confirmation screen
            updateButton.text = if (waiting) "Confirm now" else "Update the game"
            updateButton.isEnabled = waiting || !ClientBuildService.running
            updateAction = if (waiting) ({ ClientBuildService.confirmNow() })
            else ({ startForegroundService(Intent(this, ClientBuildService::class.java).putExtra(ClientBuildService.PATCH, true)) })
        }

        logTabs.forEachIndexed { i, tab -> tab.setTextColor(if (LOGS[i].first == logName) GOLD else MUTED) }
        log.text = tail(File(filesDir, "logs/$logName.log"))
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
}
