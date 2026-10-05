package io.github.natusanima.slayerrevival

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.graphics.Typeface
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.view.Gravity
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import kotlin.concurrent.thread

/**
 * Pairs the app with this phone's own Wireless debugging, so the client build can drive adb with no PC.
 * The player reads the IP:port and 6-digit code from the "Pair device with pairing code" dialog. One-time:
 * once paired, the adb key is trusted and later builds connect on their own.
 */
class PairActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val pad = (16 * resources.displayMetrics.density).toInt()
        val page = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad, pad, pad)
            fitsSystemWindows = true
        }
        page.addView(TextView(this).apply {
            text = "Pair with Wireless debugging"
            textSize = 24f
            typeface = Typeface.create(Typeface.SERIF, Typeface.BOLD)
        })
        page.addView(TextView(this).apply {
            text = "The app builds and installs the game for you using this phone's own Wireless debugging, so no " +
                "PC is needed. This is a one-time pairing.\n\n" +
                "1. Open Developer options → Wireless debugging and turn it on.\n" +
                "2. Tap “Pair device with pairing code”.\n" +
                "3. Type the IP address & port and the 6-digit code it shows below."
            setPadding(0, pad / 2, 0, pad)
        })
        page.addView(Button(this).apply {
            text = "Open Developer options"
            setOnClickListener { openDeveloperSettings() }
        })

        val address = EditText(this).apply {
            hint = "IP address and port, e.g. 192.168.1.5:41234"
            isSingleLine = true
        }
        val code = EditText(this).apply {
            hint = "Pairing code (6 digits)"
            inputType = InputType.TYPE_CLASS_NUMBER
            isSingleLine = true
        }
        page.addView(address)
        page.addView(code)

        val status = TextView(this).apply { setPadding(0, pad, 0, 0) }
        val pair = Button(this).apply { text = "Pair" }
        page.addView(pair)
        page.addView(status)

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
                    Adb.pair(this, host, port, pin)
                    Adb.connect(this) // confirm the key is now trusted
                    null
                } catch (e: Exception) {
                    e.message ?: e.javaClass.simpleName
                }
                runOnUiThread {
                    if (isFinishing) return@runOnUiThread
                    if (result == null) {
                        Toast.makeText(this, "Paired. Building the client…", Toast.LENGTH_LONG).show()
                        startForegroundService(Intent(this, ClientBuildService::class.java))
                        finish()
                    } else {
                        pair.isEnabled = true
                        status.text = "Pairing failed: $result\nThe code and port change each time the dialog opens — " +
                            "reopen it and try again."
                    }
                }
            }
        }

        setContentView(ScrollView(this).apply {
            fitsSystemWindows = true
            addView(page)
        })
    }

    private fun openDeveloperSettings() = try {
        startActivity(Intent(Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS))
    } catch (_: ActivityNotFoundException) {
        Toast.makeText(this, "Open Settings → Developer options yourself.", Toast.LENGTH_LONG).show()
    }
}
