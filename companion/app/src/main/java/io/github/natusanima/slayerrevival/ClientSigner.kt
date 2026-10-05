package io.github.natusanima.slayerrevival

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import com.android.apksig.ApkSigner
import com.android.apksig.KeyConfig
import java.io.File
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.cert.X509Certificate
import java.util.Date
import javax.security.auth.x500.X500Principal

/**
 * Signs the assembled client APK with apksig, so no JVM is needed on the phone. The key lives in the
 * AndroidKeyStore (non-exportable, hardware-backed where available) and is generated once, so rebuilt
 * clients keep the same signature. Uninstalling this app deletes the key — the game would then have to be
 * reinstalled from the Play copy and the client rebuilt, which is why the game's data is wiped on uninstall.
 */
object ClientSigner {
    private const val ALIAS = "client-signing-key"

    fun sign(unsigned: File, signed: File) {
        val cert = key()
        val config = ApkSigner.SignerConfig.Builder("CERT", KeyConfig.Jca(cert.first), listOf(cert.second)).build()
        ApkSigner.Builder(listOf(config))
            .setInputApk(unsigned)
            .setOutputApk(signed)
            .setV1SigningEnabled(false) // the game's minSdk is 24; APK Signature Scheme v2 is enough
            .setV2SigningEnabled(true)
            .setV3SigningEnabled(true)
            .setMinSdkVersion(24)
            .build()
            .sign()
    }

    private fun key(): Pair<PrivateKey, X509Certificate> {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        if (!store.containsAlias(ALIAS)) {
            val now = System.currentTimeMillis()
            val spec = KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN)
                .setKeySize(2048)
                .setDigests(KeyProperties.DIGEST_SHA256, KeyProperties.DIGEST_SHA512)
                .setSignaturePaddings(KeyProperties.SIGNATURE_PADDING_RSA_PKCS1)
                .setCertificateSubject(X500Principal("CN=Slayer Revival"))
                .setCertificateNotBefore(Date(now))
                .setCertificateNotAfter(Date(now + 30L * 365 * 24 * 60 * 60 * 1000)) // 30 years
                .build()
            KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_RSA, "AndroidKeyStore")
                .apply { initialize(spec) }.generateKeyPair()
        }
        return (store.getKey(ALIAS, null) as PrivateKey) to (store.getCertificate(ALIAS) as X509Certificate)
    }
}
