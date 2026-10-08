package io.github.natusanima.slayerrevival

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.format.Formatter
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.LinearLayout.LayoutParams
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import java.io.File
import java.io.RandomAccessFile
import java.security.MessageDigest

/**
 * The guided setup: every step from a phone with nothing on it to a playable game, in order, with the next one
 * opened. Each step reads the phone's real state, so it ticks itself off and the player can leave and come back.
 */
class SetupActivity : Activity() {
    private companion object {
        const val NEEDED = 6L shl 30 // the extra data, the built client, and room to install it
        const val GAME_SPLITS = 22 // the 21 asset-pack splits and the arm64 split of version 1.1.116

        val GAME_STEPS = listOf(
            "Tap Open in Aurora below.",
            "Sign in with Google, not Anonymous, using an account that had the game before. Signed in anonymously? Log out first.",
            "Tap the three dots at the top right, then Manual download.",
            "Enter the version code 300085. Not 1.1.116.",
            "Download and install it.",
        )
        val SIGN_IN_STEPS = listOf(
            "Tap Sign in with Google below.",
            "Sign in with the account you play with. Refused? Use one that had the game before.",
            "Follow Google's prompts. The page closes by itself.",
        )
        val BUILD_STEPS = listOf(
            "Tap Build the client. It takes a few minutes.",
            "When Android asks to uninstall the game, confirm. The client built from it replaces it.",
            "When Android asks to install the client, confirm. Told this app can't install apps? Tap Settings and allow it.",
        )

        const val SURFACE = 0xFF1E1E24.toInt()
        const val TEXT = 0xFFEDEAE4.toInt()
        const val MUTED = 0xFF9E9BA5.toInt()
        const val GOLD = 0xFFD9A441.toInt()
        const val GREEN = 0xFF72C472.toInt()
    }

    private val handler = Handler(Looper.getMainLooper())
    private val refresh = object : Runnable {
        override fun run() {
            render()
            handler.postDelayed(this, 1000)
        }
    }
    private lateinit var steps: List<Step>

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val page = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(px(16), px(20), px(16), px(16))
        }
        page.addView(text(26f, bold = true).apply {
            text = "Guided setup"
            typeface = Typeface.create(Typeface.SERIF, Typeface.BOLD)
        })
        page.addView(text(14f, MUTED).apply {
            text = "Seven steps, in order. Each one ticks itself off when it is done, so you can leave and come back."
            setPadding(0, px(6), 0, px(16))
        })
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(px(16), px(4), px(16), px(12))
            background = GradientDrawable().apply {
                setColor(SURFACE)
                cornerRadius = px(16).toFloat()
            }
        }
        page.addView(card, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT).apply { bottomMargin = px(12) })
        steps = listOf("Check this phone", "Install the game, version 1.1.116", "Sign in to Google", "Download the extra data",
            "Build and install the playable client", "Choose your map region", "Play").mapIndexed { i, title -> Step(card, i + 1, title) }
        page.addView(button("Copy debug info") { copyDebugInfo() },
            LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT).apply { gravity = Gravity.CENTER_HORIZONTAL })
        page.addView(text(12f, MUTED).apply {
            text = "Not affiliated with CD PROJEKT RED, Spokko or Google."
            gravity = Gravity.CENTER_HORIZONTAL
        })
        setContentView(ScrollView(this).apply {
            fitsSystemWindows = true
            addView(page)
        })
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
        val game = installed(MainActivity.GAME)
        val ours = game != null && !playSigned(game) // the playable client has replaced the Play copy
        val fromPlay = game != null && !ours
        val parts = game?.splitNames?.size ?: 0
        val packs = PackDownloadService.complete(this)
        val region = Maps.selected(this)
        val free = filesDir.usableSpace
        val wifi = getSystemService(ConnectivityManager::class.java).let {
            it.getNetworkCapabilities(it.activeNetwork)?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true
        }
        val built = ClientBuildService.resumable(this) // the client is built, so what it was built from may go
        val roomy = free >= NEEDED || packs || ours || built
        val gameDone = ours || built || (game != null && game.longVersionCode == MainActivity.GAME_VERSION && parts >= GAME_SPLITS)
        val signedIn = PlayAccount.signedIn(this)
        val packsDone = packs || ours || built
        val done = listOf(roomy, gameDone, signedIn || packsDone, packsDone, ours, region != null)
        val current = done.indexOfFirst { !it }.let { if (it < 0) 6 else it }
        fun at(i: Int) = i == current

        steps[0].show(roomy, at(0), "Free space: ${size(free)}. " + if (roomy) "Enough." else
            "The setup needs about ${size(NEEDED)} while it runs. Free some up, then come back.")

        val aurora = installed(MainActivity.AURORA) != null
        val auroraButton = if (aurora) "Open in Aurora" else "Get Aurora Store"
        val auroraClick = { if (aurora) openInAurora() else open(MainActivity.AURORA_SITE) }
        when {
            game == null && built -> steps[1].show(true, at(1), "Removed: the client built from it replaces it.")
            game == null -> steps[1].show(false, at(1), "The game is not installed. Any source works, as long as it is exactly " +
                "version 1.1.116 (code 300085) with all its parts. Aurora Store is one way:", auroraButton, items = GAME_STEPS, onClick = auroraClick)
            ours -> steps[1].show(true, at(1), "Replaced by the playable client.")
            game.longVersionCode != MainActivity.GAME_VERSION -> steps[1].show(false, at(1), "Version ${game.versionName} is " +
                "installed, but this needs 1.1.116 (300085). Uninstall it, then install the right one:", auroraButton,
                items = GAME_STEPS, onClick = auroraClick)
            parts < GAME_SPLITS -> steps[1].show(false, at(1), "The game is installed but incomplete: $parts of $GAME_SPLITS " +
                "parts. Uninstall it, then install the full version:", auroraButton, items = GAME_STEPS, onClick = auroraClick)
            else -> steps[1].show(true, at(1), "1.1.116 (300085) is installed." + if (fromPlay) " Tip: stop Google Play " +
                "from updating it. Open its page in the Play Store, tap the three dots, untick Enable auto update." else "",
                if (fromPlay) "Open in Play Store" else null) { openInPlay() }
        }

        val email = PlayAccount.email(this)
        when {
            email != null -> steps[2].show(true, at(2), "Signed in as $email. The app signs you out as soon as the " +
                "download is finished.", "Sign out") { PlayAccount.signOut(this) }
            packsDone -> steps[2].show(true, at(2), "Not needed any more: the extra data is on this phone.")
            else -> steps[2].show(false, at(2), "The extra data comes from Google Play, which removed the game in 2023: " +
                "it may only offer it to an account that had the game before. The app asks Google Play the way the Play " +
                "Store does. Your Google account stays on this phone, private to this app, and the app signs out when " +
                "the download ends. This phone then shows up as a Pixel 9a in your Google account's device list: you can " +
                "remove it there afterwards. This is not an official Google method: use an account you are comfortable with.",
                "Sign in with Google", items = SIGN_IN_STEPS) { startActivity(Intent(this, GoogleLoginActivity::class.java)) }
        }

        val last = PackDownloadService.status
        when {
            PackDownloadService.running -> steps[3].show(false, at(3), last ?: "Starting", "Cancel", PackDownloadService.progress) {
                startService(Intent(this, PackDownloadService::class.java).setAction(PackDownloadService.CANCEL))
            }
            packsDone -> steps[3].show(true, at(3), if (packs) "All 26 packs are on this phone." else "All 26 packs are built into the client.")
            !signedIn -> steps[3].show(false, at(3), "Sign in first.")
            else -> steps[3].show(false, at(3), "1.3 GB from Google Play." + (if (wifi) "" else " You are not on Wi-Fi.") +
                " You can leave the app: the download carries on in the background." + (last?.let { "\n\n$it" } ?: ""),
                "Download") { startForegroundService(Intent(this, PackDownloadService::class.java)) }
        }

        val building = ClientBuildService.status
        val build: () -> Unit = { startForegroundService(Intent(this, ClientBuildService::class.java)) }
        when {
            ours && ClientBuildService.running -> steps[4].show(true, at(4), building ?: "Updating…", progress = ClientBuildService.progress)
            ours -> steps[4].show(true, at(4), "Installed: the game connects to this app. After an app update, update the " +
                "game's hook too: it keeps your game data and needs no download." + (building?.let { "\n\n$it" } ?: ""),
                "Update the game's hook") {
                startForegroundService(Intent(this, ClientBuildService::class.java).setAction(ClientBuildService.REHOOK))
            }
            ClientBuildService.running -> steps[4].show(false, at(4), building ?: "Building…", progress = ClientBuildService.progress)
            !packsDone || !gameDone -> steps[4].show(false, at(4), "Finish the steps above first.")
            built -> steps[4].show(false, at(4), "The client is built. Install it to finish." + (building?.let { "\n\n$it" } ?: ""),
                "Install the client", items = BUILD_STEPS.drop(1), onClick = build)
            else -> steps[4].show(false, at(4), "The app builds the playable client on this phone from your copy of the game and " +
                "the extra data, then replaces the game with it. No computer needed." + (building?.let { "\n\n$it" } ?: ""),
                "Build the client", items = BUILD_STEPS, onClick = build)
        }

        val choose = { startActivity(Intent(this, RegionActivity::class.java)) }
        when {
            MapService.running -> steps[5].show(false, at(5), MapService.status ?: "Starting", "Cancel", MapService.progress) {
                startService(Intent(this, MapService::class.java).setAction(MapService.CANCEL))
            }
            region != null -> steps[5].show(true, at(5), "${Maps.name(this, region)}, ${size(region.length())} on this phone.",
                "Change region", onClick = choose)
            else -> steps[5].show(false, at(5), "The map comes from OpenStreetMap. Pick the region you play in: the app " +
                "downloads it from Geofabrik and builds the map on this phone." + (MapService.status?.let { "\n\n$it" } ?: ""),
                "Choose region", onClick = choose)
        }

        steps[6].show(false, at(6), "You are set. On the main screen, tap Play: the server runs on this phone while you " +
            "play, and the game connects to it.", "Back to the main screen") { finish() }
    }

    private fun installed(name: String): PackageInfo? = try {
        packageManager.getPackageInfo(name, PackageManager.GET_SIGNING_CERTIFICATES)
    } catch (_: PackageManager.NameNotFoundException) {
        null
    }

    private fun playSigned(info: PackageInfo) = info.signingInfo?.apkContentsSigners.orEmpty().any { signer ->
        MessageDigest.getInstance("SHA-256").digest(signer.toByteArray()).joinToString("") { "%02x".format(it) } == MainActivity.PLAY_CERT
    }

    private fun openInAurora() = try {
        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=${MainActivity.GAME}")).setPackage(MainActivity.AURORA))
    } catch (_: ActivityNotFoundException) {
        open(MainActivity.AURORA_SITE)
    }

    private fun openInPlay() = try {
        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=${MainActivity.GAME}")).setPackage(MainActivity.PLAY_STORE))
    } catch (_: ActivityNotFoundException) {
        Toast.makeText(this, "Google Play isn't installed on this phone.", Toast.LENGTH_LONG).show()
    }

    private fun open(url: String) = try {
        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
    } catch (_: ActivityNotFoundException) {
    }

    /** What to paste into a bug report: this phone, the game's install, and the end of the logs. No tokens are in them. */
    private fun copyDebugInfo() {
        val game = installed(MainActivity.GAME)
        val info = buildString {
            append("App ${packageManager.getPackageInfo(packageName, 0).versionName}, Android ${Build.VERSION.RELEASE} ")
            append("(SDK ${Build.VERSION.SDK_INT}), ${Build.MODEL}, free ${size(filesDir.usableSpace)}\n")
            append("Game: " + (game?.let { "${it.versionName} (${it.longVersionCode}), ${it.splitNames?.size ?: 0} splits, " +
                "${if (playSigned(it)) "Play" else "other"} signature" } ?: "not installed") + "\n")
            append("Signed in to Google: ${PlayAccount.signedIn(this@SetupActivity)}\n")
            append("Map: ${MapService.status ?: "not started"}\n")
            for (log in listOf("play", "client-build", "map-build")) append("\n-- $log.log --\n${tail(File(filesDir, "logs/$log.log"))}\n")
        }
        getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText("Debug info", info))
        Toast.makeText(this, "Copied. Paste it where you report the problem.", Toast.LENGTH_LONG).show()
    }

    private fun tail(file: File): String {
        if (!file.isFile) return "No log yet."
        RandomAccessFile(file, "r").use { f ->
            val start = maxOf(0L, f.length() - 6_000)
            val bytes = ByteArray((f.length() - start).toInt())
            f.seek(start)
            f.readFully(bytes)
            return String(bytes)
        }
    }

    private fun size(bytes: Long) = Formatter.formatShortFileSize(this, bytes)

    private fun px(dp: Int) = (dp * resources.displayMetrics.density).toInt()

    private fun text(size: Float, color: Int = TEXT, bold: Boolean = false) = TextView(this).apply {
        textSize = size
        setTextColor(color)
        if (bold) typeface = Typeface.DEFAULT_BOLD
    }

    private fun button(label: String, action: () -> Unit) = Button(this, null, 0, android.R.style.Widget_Material_Button_Borderless_Colored)
        .apply {
            text = label
            setOnClickListener { action() }
        }

    /** One step: a numbered mark (a tick once done), its title, and, while it is the one to do, what to do and the button. */
    private inner class Step(parent: LinearLayout, private val number: Int, title: String) {
        private val mark = text(13f, bold = true).apply { gravity = Gravity.CENTER }
        private val heading = text(16f, bold = true).apply { text = title }
        private val body = text(14f, MUTED)
        private val list = LinearLayout(this@SetupActivity).apply { orientation = LinearLayout.VERTICAL }
        private var listed = emptyList<String>()
        private val bar = ProgressBar(this@SetupActivity, null, 0, android.R.style.Widget_Material_ProgressBar_Horizontal)
            .apply { max = 100 }
        private val action = button("") {}.apply { setPadding(0, paddingTop, paddingRight, paddingBottom) }

        init {
            val column = LinearLayout(this@SetupActivity).apply { orientation = LinearLayout.VERTICAL }
            column.addView(heading)
            column.addView(body)
            column.addView(list)
            column.addView(bar)
            column.addView(action, LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT))
            val row = LinearLayout(this@SetupActivity).apply { setPadding(0, px(12), 0, 0) }
            row.addView(mark, LayoutParams(px(24), px(24)).apply { marginEnd = px(12) })
            row.addView(column, LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f))
            parent.addView(row)
        }

        fun show(done: Boolean, current: Boolean, message: String, label: String? = null, progress: Int? = null,
                 items: List<String> = emptyList(), onClick: () -> Unit = {}) {
            val open = current || done // a step still to come shows only its title
            val shown = if (current) items else emptyList()
            if (shown != listed) { // the screen refreshes every second: rebuild the rows only when they change
                listed = shown
                list.removeAllViews()
                shown.forEachIndexed { i, item ->
                    val row = LinearLayout(this@SetupActivity).apply { setPadding(0, px(6), 0, 0) }
                    row.addView(text(14f, GOLD, bold = true).apply { text = "${i + 1}." }, LayoutParams(px(24), LayoutParams.WRAP_CONTENT))
                    row.addView(text(14f).apply { text = item }, LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f))
                    list.addView(row)
                }
            }
            mark.text = if (done) "✓" else "$number"
            mark.setTextColor(if (done) SURFACE else GOLD)
            mark.background = GradientDrawable().apply {
                shape = GradientDrawable.OVAL
                if (done) setColor(GREEN) else setStroke(px(1).coerceAtLeast(2), if (current) GOLD else MUTED)
            }
            heading.setTextColor(if (open) TEXT else MUTED)
            body.visibility = if (open) View.VISIBLE else View.GONE
            body.text = message
            bar.visibility = if (progress == null || !open) View.GONE else View.VISIBLE
            if (progress != null) {
                bar.isIndeterminate = progress < 0
                bar.progress = progress.coerceAtLeast(0)
            }
            action.visibility = if (label == null || !open) View.GONE else View.VISIBLE
            action.text = label
            action.setOnClickListener { onClick() }
        }
    }
}
