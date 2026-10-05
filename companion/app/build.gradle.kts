import java.util.Properties

plugins {
    id("com.android.application")
}

// The release key stays in local/keys/ (never committed). companion.properties names the keystore, its alias
// and its password. Lose it and installed copies can no longer update: keep a backup.
val releaseKey = rootDir.resolve("../local/keys/companion.properties")

android {
    namespace = "io.github.natusanima.slayerrevival"
    compileSdk = 36

    defaultConfig {
        applicationId = "io.github.natusanima.slayerrevival"
        minSdk = 30 // Android 11: the oldest the phone runtime has been tried on
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
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
    implementation("com.github.MuntashirAkon:libadb-android:3.1.1") // drive the phone's own adb over Wireless debugging
    implementation("com.github.MuntashirAkon:sun-security-android:1.1") // X.509 cert for the adb key
    implementation("org.conscrypt:conscrypt-android:2.5.3") // TLS for adb pairing/connect on this device
    implementation("com.android.tools.build:apksig:8.13.2") // sign the built client APK (no JVM needed on the phone)
}
