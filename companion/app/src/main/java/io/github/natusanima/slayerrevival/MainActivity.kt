package io.github.natusanima.slayerrevival

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.graphics.Typeface
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.io.File

class MainActivity : Activity() {
    companion object {
        const val GAME = "com.spokko.witchermonsterslayer"
        const val PLAY = "io.github.natusanima.slayerrevival.PLAY"
    }

    private var playing = false

    private lateinit var status: TextView
    private lateinit var log: TextView
    private val handler = Handler(Looper.getMainLooper())
    private val refresh = object : Runnable {
        override fun run() {
            render()
            handler.postDelayed(this, 1000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 0)
        val pad = (16 * resources.displayMetrics.density).toInt()
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad, pad, pad)
            fitsSystemWindows = true
        }
        status = TextView(this).apply { textSize = 18f }
        root.addView(status)
        root.addView(button("Play") { play() })
        root.addView(button("Start server") { startForegroundService(Intent(this, ServerService::class.java)) })
        root.addView(button("Stop server") { startService(Intent(this, ServerService::class.java).setAction(ServerService.STOP)) })
        log = TextView(this).apply {
            typeface = Typeface.MONOSPACE
            textSize = 10f
        }
        root.addView(ScrollView(this).apply { addView(log) }, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        setContentView(root)
        if (intent?.action == PLAY) play()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (intent.action == PLAY) play()
    }

    /** Starts the server, then opens the game once it answers. */
    private fun play() {
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

    private fun button(text: String, action: () -> Unit) = Button(this).apply {
        this.text = text
        setOnClickListener { action() }
    }

    private fun render() {
        status.text = "Server: ${ServerService.status}"
        if (playing && ServerService.status == "Running") {
            playing = false
            packageManager.getLaunchIntentForPackage(GAME)?.let(::startActivity)
        }
        val file = File(filesDir, "logs/server.log")
        log.text = if (file.exists()) file.readLines().takeLast(60).joinToString("\n") else ""
    }
}
