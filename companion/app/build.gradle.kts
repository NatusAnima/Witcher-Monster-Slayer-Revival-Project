plugins {
    id("com.android.application")
}

android {
    namespace = "io.github.natusanima.slayerrevival"
    compileSdk = 36

    defaultConfig {
        applicationId = "io.github.natusanima.slayerrevival"
        minSdk = 30 // Wireless debugging (used by setup) arrived in Android 11
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
    }

    // The phone runtime (musl loader, .NET server, Python and the map services) is assembled into local/
    // by companion/runtime/build_runtime.py; it is never committed.
    sourceSets["main"].jniLibs.directories.add(rootDir.resolve("../local/companion/jniLibs").path)
    sourceSets["main"].assets.directories.add(rootDir.resolve("../local/companion/assets").path)

    packaging {
        jniLibs {
            useLegacyPackaging = true // extracted at install: the server and Python are executed from there
            keepDebugSymbols += "**/*.so" // never strip: libserver.so carries the .NET bundle after its ELF image
        }
    }
}
