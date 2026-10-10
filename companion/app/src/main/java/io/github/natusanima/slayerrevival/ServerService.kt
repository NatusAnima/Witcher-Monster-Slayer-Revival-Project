package io.github.natusanima.slayerrevival

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.util.Base64
import java.io.File
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.URL
import java.security.SecureRandom
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

/** Runs the game server on this phone while the player plays; the game's hook connects to it on loopback. */
class ServerService : Service() {
    companion object {
        const val STOP = "io.github.natusanima.slayerrevival.STOP"
        const val RELOAD_MAP = "io.github.natusanima.slayerrevival.RELOAD_MAP"
        const val GAME_PORT = 4253
        const val HTTP_PORT = 18080
        const val TILE_PORT = 18082
        const val ADMIN_PORT = 18092
        const val PLACEMENT_PORT = 18093
        /** Where the game's hook sends its own log (see LogSink below); the hook has the same number. */
        const val LOG_PORT = 18094

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

        /** If the server is running, starts its map services again on the map just chosen (they read it once, when they start). */
        fun reloadMap(context: Context): Boolean {
            if (status == "Stopped" || status.startsWith("Failed")) return false
            context.startService(Intent(context, ServerService::class.java).setAction(RELOAD_MAP))
            return true
        }
    }

    private val processes = mutableListOf<Process>()
    private val named = mutableMapOf<String, Process>() // the live child of each name, guarded by lock
    private val lock = Any() // guards processes, launching and the flip of stopping
    private var launching = false
    @Volatile private var stopping = false
    private var sink: ServerSocket? = null

    override fun onBind(intent: Intent?) = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        if (intent?.action == RELOAD_MAP) {
            thread(name = "map-restart") { restartMap() }
            return START_NOT_STICKY
        }
        startForeground(1, notification(status.takeUnless { it == "Stopped" } ?: "Starting"), ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        synchronized(lock) {
            // a second tap (or Play) while this one is still starting, or while the children run, must not start another set
            if (!launching && processes.none { it.isAlive }) {
                launching = true
                processes.clear()
                named.clear()
                thread(name = "server-launch") {
                    try {
                        launch()
                    } finally {
                        synchronized(lock) { launching = false }
                    }
                }
            }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        synchronized(lock) {
            stopping = true
            processes.forEach { it.destroy() }
            processes.clear()
        }
        try {
            sink?.close()
        } catch (_: Exception) {
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
            // the update's own notes for What's new, replaced every time (NewsFeed shows them before the owner's news)
            File(rt, "defaults/news/release.json").copyTo(File(state, "news/release.json"), overwrite = true)
            // trinkets only ever gain rows (the server refuses a changed or missing one) and the dashboard never edits
            // them, so each update's new trinkets replace the copy too
            File(rt, "defaults/tasks/trinkets.json").copyTo(File(state, "tasks/trinkets.json"), overwrite = true)
            val world = File(state, "world").apply { mkdirs() }
            File(world, "world.json").takeUnless { it.exists() }
                ?.writeText("{\n  \"schemaVersion\": 1,\n  \"monsterSlotsPerCell\": 18\n}\n")
            val key = File(state, "admin/proxy.key")
            if (!key.exists()) {
                key.parentFile!!.mkdirs()
                val bytes = ByteArray(36).also { SecureRandom().nextBytes(it) }
                key.writeText(Base64.encodeToString(bytes, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING))
            }
            startSink()
            val mapped = startMap(rt, world)
            start("server", "libserver.so", listOf(
                "--Http:Port", "$HTTP_PORT", "--GameServer:Port", "$GAME_PORT",
                "--LocalProfile:DataDirectory", "$state/profiles", "--LocalProfile:NewProfileMode", "reconstructed",
                "--News:Directory", "$state/news", "--Tasks:Directory", "$state/tasks", "--World:Directory", "$world",
                "--Playable:Url", "http://127.0.0.1:$PLACEMENT_PORT",
                // real weather: free, no key; the server sends only the position rounded to 0.1° (about 11 km)
                "--Weather:Url", "https://api.open-meteo.com/v1/forecast",
                "--Admin:Port", "$ADMIN_PORT", "--Admin:Origin", "http://127.0.0.1:$ADMIN_PORT", // DashboardActivity
                "--Admin:KeyFile", "$key", "--Admin:DataDirectory", "$state/admin/data",
                "--Admin:DebugTools", "true", // the Players tab's debug tools: the phone is the player's own server
                // one timestamped line per entry: the log is read by people and by the bug report
                "--Logging:Console:FormatterOptions:SingleLine", "true",
                "--Logging:Console:FormatterOptions:TimestampFormat", "HH:mm:ss.fff ",
            ), mapOf("ASPNETCORE_ENVIRONMENT" to "Production", "DOTNET_EnableDiagnostics" to "0",
                "SSL_CERT_FILE" to "$rt/etc/ca-certificates.crt") + SERVER_MEMORY)
            thread(name = "recorder") { // what the phone was doing around a crash: memory, the server's processes, heat
                while (!stopping) {
                    EventLog.sample(this)
                    Thread.sleep(15_000)
                }
            }
            settle(mapped)
        } catch (e: Exception) {
            update("Failed: ${e.message}")
        }
    }

    /** Starts the tile and placement services on the chosen map; false if no map is chosen yet. */
    private fun startMap(rt: File, world: File): Boolean {
        val index = Maps.selected(this) ?: return false
        val maps = File(rt, "maps/map-road-fixture-01")
        val python = mapOf("PYTHONHOME" to "$rt/python", "PYTHONUNBUFFERED" to "1")
        start("tiles", "libpython.so", listOf("$maps/osm_live_sidecar.py", "--bind", "127.0.0.1",
            "--port", "$TILE_PORT", "--index", "$index", "--cache-dir", "$cacheDir/tiles", "--offline"), python)
        start("placement", "libpython.so", listOf("$maps/playable_locations.py", "--index", "$index",
            "--port", "$PLACEMENT_PORT", "--policy", "$world/placement-policy.json",
            "--tuning", "$world/tuning.json"), python)
        return true
    }

    private fun settle(mapped: Boolean) = update(when {
        !healthy("http://127.0.0.1:$HTTP_PORT/health") -> "Server did not answer: see its log"
        !mapped -> "Running without a map: choose a region"
        !listening(TILE_PORT) || !listening(PLACEMENT_PORT) -> "Map services did not start: see their logs"
        else -> "Running"
    })

    /** A map was built while the server runs: its tile and placement services start again, on the new map. The game's server stays up. */
    private fun restartMap() {
        while (synchronized(lock) { launching } && !stopping) Thread.sleep(500) // a start in progress finishes first
        val old = synchronized(lock) {
            if (stopping) return
            if (processes.none { it.isAlive }) { // no start behind this request: nothing to restart
                stopSelf()
                return
            }
            listOf("tiles", "placement").mapNotNull { named.remove(it) }.also { processes.removeAll(it) }
        }
        old.forEach { it.destroy() }
        old.forEach { it.waitFor() } // the ports are free again before the new ones bind them
        try {
            settle(startMap(Runtime.prepare(this), File(filesDir, "state/world")))
        } catch (e: Exception) {
            update("Failed: ${e.message}")
        }
    }

    /** Keeps the last two runs of a log: name.log becomes name.prev.log, and that becomes name.prev2.log. */
    private fun rotate(log: File) {
        if (!log.exists()) return
        val base = log.name.removeSuffix(".log")
        File(log.parentFile, "$base.prev.log").takeIf { it.exists() }?.renameTo(File(log.parentFile, "$base.prev2.log"))
        log.renameTo(File(log.parentFile, "$base.prev.log"))
    }

    private fun start(name: String, program: String, args: List<String>, env: Map<String, String>) {
        val log = File(filesDir, "logs/$name.log")
        rotate(log)
        val process = synchronized(lock) {
            if (stopping) return // stopped while starting: a child registered now would outlive the service
            Runtime.start(this, program, args, log, env).also { processes += it; named[name] = it }
        }
        EventLog.write(this, "server", "$name started")
        thread(name = "$name-watch") {
            val code = process.waitFor()
            EventLog.write(this, "server", "$name exited with code $code")
            // a child replaced on purpose (restartMap) is no longer the one registered under its name
            if (!stopping && synchronized(lock) { named[name] === process }) update("$name exited with code $code: see its log")
        }
    }

    /**
     * Takes the game hook's log over loopback into logs/game.log, so a bug report holds the game's side of a crash. Any app on the
     * phone can connect to a loopback port, so lines and the file are capped and only a few connections are served.
     */
    private fun startSink() {
        val log = File(filesDir, "logs/game.log")
        rotate(log)
        val socket = try {
            ServerSocket(LOG_PORT, 4, InetAddress.getByName("127.0.0.1"))
        } catch (e: Exception) {
            EventLog.write(this, "server", "the game log port $LOG_PORT is not available: $e")
            return
        }
        sink = socket
        val open = AtomicInteger()
        val time = SimpleDateFormat("MM-dd HH:mm:ss.SSS", Locale.US)
        thread(name = "game-log") {
            while (!stopping) {
                val client = try {
                    socket.accept()
                } catch (_: Exception) {
                    break
                }
                if (open.incrementAndGet() > 4) {
                    open.decrementAndGet()
                    client.close()
                    continue
                }
                thread(name = "game-log-client") {
                    EventLog.write(this, "game", "the game's hook connected")
                    try {
                        receive(client, log, time)
                    } finally {
                        open.decrementAndGet()
                        EventLog.write(this, "game", "the game's hook disconnected")
                    }
                }
            }
        }
    }

    private fun receive(client: Socket, log: File, time: SimpleDateFormat) {
        try {
            client.soTimeout = 120_000 // the hook sends a heartbeat every 10 s
            val input = client.getInputStream().bufferedReader()
            val line = StringBuilder()
            fun flush() {
                if (line.isEmpty()) return
                synchronized(log) {
                    if (log.length() > 2_000_000) log.renameTo(File(log.parentFile, "game.prev.log"))
                    log.appendText("${time.format(Date())} $line\n")
                }
                line.setLength(0)
            }
            while (true) {
                val c = input.read()
                if (c < 0) break
                if (c == '\n'.code) flush() else if (line.length < 8_000) line.append(c.toChar())
            }
            flush()
        } catch (_: Exception) {
            // a dropped connection ends the game's session
        } finally {
            client.close()
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
        if (stopping && text != "Stopped") return // a late launch step must not overwrite "Stopped"
        status = text
        EventLog.write(this, "server", text)
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
