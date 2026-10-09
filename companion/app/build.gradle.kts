import java.util.Properties

plugins {
    id("com.android.application")
}

// The release key stays in local/keys/ (never committed). companion.properties names the keystore, its alias
// and its password. Lose it and installed copies can no longer update: keep a backup.
val releaseKey = rootDir.resolve("../local/keys/companion.properties")

// x.y.z. x: the stage (alpha, beta, ...). y: raise it for a release that touches the game itself; the app then updates
// the installed game in place. z: raise it for a change to the app alone, which leaves the game as it is.
// Tag the GitHub release v<version>. versionCode is derived from it, so y and z stay below 100.
val appVersion = "0.2.0"

android {
    namespace = "io.github.natusanima.slayerrevival"
    compileSdk = 36

    defaultConfig {
        applicationId = "io.github.natusanima.slayerrevival"
        minSdk = 30 // Android 11: the oldest the phone runtime has been tried on
        targetSdk = 36
        versionCode = appVersion.split('.').map(String::toInt).let { (x, y, z) -> x * 10_000 + y * 100 + z }
        versionName = appVersion
        // The runtime is arm64-only: a phone with another ABI should refuse the install, not crash at start.
        ndk { abiFilters += "arm64-v8a" }
    }

    signingConfigs {
        if (releaseKey.isFile) create("release") {
            val key = Properties().apply { releaseKey.inputStream().use { load(it) } }
            storeFile = releaseKey.resolveSibling(key.getProperty("storeFile"))
            storePassword = key.getProperty("password")
            keyAlias = key.getProperty("alias")
            keyPassword = key.getProperty("password")
        }
    }

    buildTypes {
        getByName("release") {
            signingConfig = signingConfigs.findByName("release")
        }
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

dependencies {
    implementation("com.android.tools.build:apksig:8.13.2") // sign the built client APK (no JVM needed on the phone)
    implementation("com.auroraoss:gplayapi:3.6.4") // Google Play sign-in and device registration, to fetch the game's extra data
}
