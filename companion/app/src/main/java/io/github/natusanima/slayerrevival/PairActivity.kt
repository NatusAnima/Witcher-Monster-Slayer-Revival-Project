package io.github.natusanima.slayerrevival

import android.app.Activity
import android.app.NotificationManager
import android.content.ActivityNotFoundException
import android.content.Intent
import android.graphics.Typeface
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.InputType
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import kotlin.concurrent.thread

/**
 * Pairs the app with this phone's own Wireless debugging, so the client build can drive adb with no PC. One-time:
 * once paired, the adb key is trusted and later builds connect on their own.
 *
 * Android closes its pairing dialog when the player leaves Settings, so the code is typed into a notification
 * (PairingService), not into this screen. Typing the address and the code here stays as a fallback.
 */
class PairActivity : Activity() {
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var progress: TextView
    private lateinit var hints: TextView
    private val refresh = object : Runnable {
        override fun run() {
            progress.text = PairingService.status.orEmpty()
            hints.text = problems().joinToString("\n\n")
            if (ClientBuildService.running) finish() // paired: the main screen shows the build
            else handler.postDelayed(this, 1000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val page = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(px(16), px(16), px(16), px(16))
        }
        page.addView(TextView(this).apply {
            text = "Pair with Wireless debugging"
            textSize = 24f
            typeface = Typeface.create(Typeface.SERIF, Typeface.BOLD)
        })
        page.addView(TextView(this).apply {
            text = "The app builds and installs the game for you using this phone's own Wireless debugging, so no PC " +
                "is needed. You pair once, and it takes about a minute."
            setPadding(0, px(8), 0, px(8))
        })
        page.addView(steps(
            "Tap Start pairing. Settings opens.",
            "Turn on Wireless debugging. It needs Wi-Fi.",
            "Tap Pair device with pairing code.",
            "Pull down the notification shade and type the 6-digit code there.",
        ))
        page.addView(Button(this).apply {
            text = "Start pairing"
            setOnClickListener {
                startForegroundService(Intent(this@PairActivity, PairingService::class.java))
                openWirelessDebugging()
            }
        })
        progress = TextView(this).apply { setPadding(0, px(8), 0, 0) }
        hints = TextView(this).apply { setPadding(0, px(8), 0, 0) }
        page.addView(progress)
        page.addView(hints)

        val manual = manualPairing()
        manual.visibility = View.GONE
        page.addView(Button(this).apply {
            text = "Pair by typing the address and code instead"
            setOnClickListener {
                visibility = View.GONE
                manual.visibility = View.VISIBLE
            }
        })
        page.addView(manual)

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

    /** What would stop the pairing before it starts: each with its fix, or nothing. */
    private fun problems(): List<String> = buildList {
        if (Settings.Global.getInt(contentResolver, Settings.Global.DEVELOPMENT_SETTINGS_ENABLED, 0) == 0) {
            add("Developer options are off. Open Settings → About phone and tap the version number seven times.")
        }
        val network = getSystemService(ConnectivityManager::class.java)
        if (network.getNetworkCapabilities(network.activeNetwork)?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) != true) {
            add("Connect to Wi-Fi first: Wireless debugging only works on Wi-Fi.")
        }
        if (!getSystemService(NotificationManager::class.java).areNotificationsEnabled()) {
            add("Notifications are off for this app, and the code is typed into one. Turn them on in the app's " +
                "settings, or pair by typing the address and code.")
        }
    }

    /** Straight to the Wireless debugging page when this phone's Settings has one, else to Developer options. */
    private fun openWirelessDebugging() {
        try {
            startActivity(Intent().setClassName("com.android.settings", "com.android.settings.Settings" + '$' + "WirelessDebuggingActivity"))
        } catch (_: Exception) {
            try {
                startActivity(Intent(Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS))
            } catch (_: ActivityNotFoundException) {
                Toast.makeText(this, "Open Settings → Developer options yourself.", Toast.LENGTH_LONG).show()
            }
        }
    }

    /** The fallback: the player reads the IP:port and the code from the pairing dialog and types them. */
    private fun manualPairing() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        val address = EditText(context).apply {
            hint = "IP address and port, e.g. 192.168.1.5:41234"
            isSingleLine = true
        }
        val code = EditText(context).apply {
            hint = "Pairing code (6 digits)"
            inputType = InputType.TYPE_CLASS_NUMBER
            isSingleLine = true
        }
        val status = TextView(context).apply { setPadding(0, px(8), 0, 0) }
        val pair = Button(context).apply { text = "Pair" }
        addView(TextView(context).apply {
            text = "The dialog closes when you leave Settings, so open this screen in a pop-up or split-screen window " +
                "next to it, and read the address and code from the dialog."
            setPadding(0, px(8), 0, 0)
        })
        addView(address)
        addView(code)
        addView(pair)
        addView(status)
        pair.setOnClickListener {
            val host = address.text.toString().substringBefore(':').trim()
            val port = address.text.toString().substringAfter(':', "").trim().toIntOrNull()
            val pin = code.text.toString().trim()
            if (host.isEmpty() || port == null || pin.length < 6) {
                status.text = "Enter the IP:port and the 6-digit code exactly as the dialog shows them."
                return@setOnClickListener
            }
            pair.isEnabled = false
            status.text = "Pairing…"
            thread(name = "pair") {
                val result = try {
                    Adb.pair(this@PairActivity, host, port, pin)
                    Adb.connect(this@PairActivity) // confirm the key is now trusted
                    null
                } catch (e: Exception) {
                    e.message ?: e.javaClass.simpleName
                }
                runOnUiThread {
                    if (isFinishing) return@runOnUiThread
                    if (result == null) {
                        Toast.makeText(this@PairActivity, "Paired. Building the client…", Toast.LENGTH_LONG).show()
                        startForegroundService(Intent(this@PairActivity, ClientBuildService::class.java))
                        finish()
                    } else {
                        pair.isEnabled = true
                        status.text = "Pairing failed: $result\nThe code and port change each time the dialog opens: " +
                            "reopen it and try again."
                    }
                }
            }
        }
    }

    /** Short numbered steps, one action each; a wrapped line stays under its own text, not under the number. */
    private fun steps(vararg items: String) = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(0, 0, 0, px(8))
        items.forEachIndexed { i, item ->
            val row = LinearLayout(context).apply { setPadding(0, px(6), 0, 0) }
            row.addView(TextView(context).apply {
                text = "${i + 1}."
                typeface = Typeface.DEFAULT_BOLD
            }, LinearLayout.LayoutParams(px(24), LinearLayout.LayoutParams.WRAP_CONTENT))
            row.addView(TextView(context).apply { text = item },
                LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
            addView(row)
        }
    }

    private fun px(dp: Int) = (dp * resources.displayMetrics.density).toInt()
}
