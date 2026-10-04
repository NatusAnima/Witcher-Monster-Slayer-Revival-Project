package io.github.natusanima.slayerrevival

import android.content.Context
import java.io.File
import java.util.zip.ZipInputStream

/**
 * The phone runtime: Alpine (musl) builds of the .NET server and Python, assembled by
 * companion/runtime/build_runtime.py.
 *
 * Programs ship in the native library folder, the only app-owned place Android lets an app execute
 * files from. Their ELF interpreter is the relative name "libmusl.so" (musl's loader, shipped next to
 * them), which the kernel resolves against the working directory, so they always start from that folder.
 * Shared libraries, the Python standard library and the map scripts come from assets/runtime.zip,
 * unpacked into files/rt on first start and again after every app update.
 */
object Runtime {
    fun root(context: Context) = File(context.filesDir, "rt")

    @Synchronized
    fun prepare(context: Context): File {
        val root = root(context)
        val stamp = File(root, ".stamp")
        val version = context.packageManager.getPackageInfo(context.packageName, 0).lastUpdateTime.toString()
        if (stamp.isFile && stamp.readText() == version) return root
        root.deleteRecursively()
        val base = root.canonicalPath + File.separator
        ZipInputStream(context.assets.open("runtime.zip").buffered()).use { zip ->
            while (true) {
                val entry = zip.nextEntry ?: break
                val file = File(root, entry.name)
                check(file.canonicalPath.startsWith(base)) { "runtime.zip: bad entry ${entry.name}" }
                if (entry.isDirectory) file.mkdirs()
                else {
                    file.parentFile!!.mkdirs()
                    file.outputStream().use { zip.copyTo(it) }
                }
            }
        }
        stamp.writeText(version)
        return root
    }

    /** Starts one of the shipped programs (libserver.so, libpython.so) with its output appended to [log]. */
    fun start(context: Context, program: String, args: List<String>, log: File, env: Map<String, String> = emptyMap()): Process {
        val libDir = context.applicationInfo.nativeLibraryDir
        log.parentFile!!.mkdirs()
        return ProcessBuilder(listOf("$libDir/$program") + args)
            .directory(File(libDir))
            .redirectErrorStream(true)
            .redirectOutput(ProcessBuilder.Redirect.appendTo(log))
            .apply {
                environment().putAll(mapOf(
                    "LD_LIBRARY_PATH" to "${root(context)}/lib",
                    "HOME" to context.filesDir.path,
                    "TMPDIR" to context.cacheDir.path,
                    // Answers the syscalls Android's app seccomp filter would kill us for (see seccomp_shim.c).
                    "LD_PRELOAD" to "$libDir/libseccompshim.so",
                ) + env)
            }
            .start()
    }
}
