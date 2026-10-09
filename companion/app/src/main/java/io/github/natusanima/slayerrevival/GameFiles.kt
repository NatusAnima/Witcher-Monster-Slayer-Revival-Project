package io.github.natusanima.slayerrevival

import android.content.pm.PackageInfo
import java.util.zip.ZipFile

/**
 * What the installed game holds that the client build needs. Opening an APK's zip directory takes a moment and the setup
 * screen asks every second, so the answer is kept per install.
 */
object GameFiles {
    private const val LIBIL2CPP = "lib/arm64-v8a/libil2cpp.so"
    private const val ARM64_SPLIT = "config.arm64_v8a"

    private var cached: Pair<Long, Boolean>? = null

    /** True if the arm64 libraries are there: in the arm64 split (Aurora, a bundle) or inside a single APK (a universal build). */
    @Synchronized
    fun hasLibraries(info: PackageInfo): Boolean {
        cached?.let { (stamp, answer) -> if (stamp == info.lastUpdateTime) return answer }
        val answer = info.splitNames.orEmpty().contains(ARM64_SPLIT) || try {
            ZipFile(info.applicationInfo?.sourceDir ?: return false).use { it.getEntry(LIBIL2CPP) != null }
        } catch (_: Exception) {
            false
        }
        cached = info.lastUpdateTime to answer
        return answer
    }
}
