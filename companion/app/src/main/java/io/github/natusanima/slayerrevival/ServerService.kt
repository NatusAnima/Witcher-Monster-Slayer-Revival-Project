package io.github.natusanima.slayerrevival

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.util.Base64
import java.io.File
import java.net.HttpURLConnection
import java.net.InetSocketAddress
import java.net.Socket
import java.net.URL
import java.security.SecureRandom
import kotlin.concurrent.thread

/** Runs the game server on this phone while the player plays; the game's hook connects to it on loopback. */
class ServerService : Service() {
    companion object {
        const val STOP = "io.github.natusanima.slayerrevival.STOP"
        const val GAME_PORT = 4253
        const val HTTP_PORT = 18080
        const val TILE_PORT = 18082
        const val ADMIN_PORT = 18092
        const val PLACEMENT_PORT = 18093

        /**
         * The server shares the phone with the game, so its .NET heap is kept small: workstation GC
         * without the background GC thread, compacting eagerly, and a hard ceiling on the managed
         * heap (the server's data is a few MB; the ceiling only stops the GC from letting garbage
         * pile up because the phone has free RAM at that moment). Values are hex, as .NET reads them.
         */
        private val SERVER_MEMORY = mapOf(
            "DOTNET_gcServer" to "0",
            "DOTNET_gcConcurrent" to "0",
            "DOTNET_GCConserveMemory" to "7",
            "DOTNET_GCHeapHardLimit" to "0x10000000", // 256 MB
            "DOTNET_TieredPGO" to "0", // no profiling instrumentation kept per method
        )

        @Volatile
        var status = "Stopped"
            private set
    }

    private val processes = mutableListOf<Process>()
    @Volatile private var stopping = false

    override fun onBind(intent: Intent?) = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        startForeground(1, notification(status.takeUnless { it == "Stopped" } ?: "Starting"), ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        synchronized(processes) {
            if (processes.isEmpty()) thread(name = "server-launch") { launch() }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        stopping = true
        synchronized(processes) {
            processes.forEach { it.destroy() }
            processes.clear()
        }
        update("Stopped")
        super.onDestroy()
    }

    private fun launch() {
        try {
            update("Preparing")
            val rt = Runtime.prepare(this)
            val state = File(filesDir, "state")
            for (name in listOf("news", "tasks")) { // working copies, so edits never touch the shipped defaults
                val dir = File(state, name)
                if (!dir.isDirectory) File(rt, "defaults/$name").copyRecursively(dir)
            }
            val world = File(state, "world").apply { mkdirs() }
            File(world, "world.json").takeUnless { it.exists() }
                ?.writeText("{\n  \"schemaVersion\": 1,\n  \"monsterSlotsPerCell\": 18\n}\n")
            val key = File(state, "admin/proxy.key")
            if (!key.exists()) {
                key.parentFile!!.mkdirs()
                val bytes = ByteArray(36).also { SecureRandom().nextBytes(it) }
                key.writeText(Base64.encodeToString(bytes, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING))
            }
            val index = Maps.selected(this)
            if (index != null) {
                val maps = File(rt, "maps/map-road-fixture-01")
                val python = mapOf("PYTHONHOME" to "$rt/python", "PYTHONUNBUFFERED" to "1")
                start("tiles", "libpython.so", listOf("$maps/osm_live_sidecar.py", "--bind", "127.0.0.1",
                    "--port", "$TILE_PORT", "--index", "$index", "--cache-dir", "$cacheDir/tiles", "--offline"), python)
                start("placement", "libpython.so", listOf("$maps/playable_locations.py", "--index", "$index",
                    "--port", "$PLACEMENT_PORT", "--policy", "$world/placement-policy.json"), python)
            }
            start("server", "libserver.so", listOf(
                "--Http:Port", "$HTTP_PORT", "--GameServer:Port", "$GAME_PORT",
                "--LocalProfile:DataDirectory", "$state/profiles", "--LocalProfile:NewProfileMode", "reconstructed",
                "--News:Directory", "$state/news", "--Tasks:Directory", "$state/tasks", "--World:Directory", "$world",
                "--Playable:Url", "http://127.0.0.1:$PLACEMENT_PORT",
                "--Admin:Port", "$ADMIN_PORT", "--Admin:Origin", "http://127.0.0.1:$ADMIN_PORT", // DashboardActivity
                "--Admin:KeyFile", "$key", "--Admin:DataDirectory", "$state/admin/data",
            ), mapOf("ASPNETCORE_ENVIRONMENT" to "Production", "DOTNET_EnableDiagnostics" to "0") + SERVER_MEMORY)
            update(when {
                !healthy("http://127.0.0.1:$HTTP_PORT/health") -> "Server did not answer: see its log"
                index == null -> "Running without a map: choose a region"
                !listening(TILE_PORT) || !listening(PLACEMENT_PORT) -> "Map services did not start: see their logs"
                else -> "Running"
            })
        } catch (e: Exception) {
            update("Failed: ${e.message}")
        }
    }

    private fun start(name: String, program: String, args: List<String>, env: Map<String, String>) {
        val log = File(filesDir, "logs/$name.log")
        if (log.exists()) log.renameTo(File(log.parentFile, "$name.prev.log"))
        val process = Runtime.start(this, program, args, log, env)
        synchronized(processes) { processes += process }
        thread(name = "$name-watch") {
            val code = process.waitFor()
            if (!stopping) update("$name exited with code $code: see its log")
        }
    }

    private fun healthy(url: String): Boolean {
        repeat(120) {
            if (stopping) return false
            try {
                val connection = URL(url).openConnection() as HttpURLConnection
                connection.connectTimeout = 1000
                connection.readTimeout = 2000
                if (connection.responseCode == 200) return true
            } catch (_: Exception) {
            }
            Thread.sleep(500)
        }
        return false
    }

    private fun listening(port: Int): Boolean {
        repeat(60) {
            if (stopping) return false
            try {
                Socket().use { it.connect(InetSocketAddress("127.0.0.1", port), 1000) }
                return true
            } catch (_: Exception) {
            }
            Thread.sleep(500)
        }
        return false
    }

    private fun update(text: String) {
        status = text
        if (!stopping) getSystemService(NotificationManager::class.java).notify(1, notification(text))
    }

    private fun notification(text: String): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("server", "Game server", NotificationManager.IMPORTANCE_LOW))
        val stop = PendingIntent.getService(this, 0, Intent(this, ServerService::class.java).setAction(STOP),
            PendingIntent.FLAG_IMMUTABLE)
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, "server")
            .setSmallIcon(android.R.drawable.stat_sys_upload_done)
            .setContentTitle("Game server")
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
            .addAction(Notification.Action.Builder(null, "Stop", stop).build())
            .build()
    }
}
