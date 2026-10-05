package io.github.natusanima.slayerrevival

import android.content.Context
import android.os.Build
import android.provider.Settings
import android.sun.security.x509.AlgorithmId
import android.sun.security.x509.CertificateAlgorithmId
import android.sun.security.x509.CertificateExtensions
import android.sun.security.x509.CertificateIssuerName
import android.sun.security.x509.CertificateSerialNumber
import android.sun.security.x509.CertificateSubjectName
import android.sun.security.x509.CertificateValidity
import android.sun.security.x509.CertificateVersion
import android.sun.security.x509.CertificateX509Key
import android.sun.security.x509.KeyIdentifier
import android.sun.security.x509.PrivateKeyUsageExtension
import android.sun.security.x509.SubjectKeyIdentifierExtension
import android.sun.security.x509.X500Name
import android.sun.security.x509.X509CertImpl
import android.sun.security.x509.X509CertInfo
import io.github.muntashirakon.adb.AbsAdbConnectionManager
import io.github.muntashirakon.adb.AdbPairingRequiredException
import io.github.muntashirakon.adb.AdbStream
import org.conscrypt.Conscrypt
import java.io.File
import java.io.IOException
import java.io.OutputStream
import java.security.KeyFactory
import java.security.KeyPairGenerator
import java.security.PrivateKey
import java.security.SecureRandom
import java.security.Security
import java.security.cert.Certificate
import java.security.cert.CertificateFactory
import java.security.spec.PKCS8EncodedKeySpec
import java.util.Date
import java.util.Random
import java.util.concurrent.TimeUnit

/** Wireless debugging is switched off, so there is no daemon to find: the player turns it on, and pairs the first time. */
class WirelessDebuggingOff : AdbPairingRequiredException("Wireless debugging is off")

/**
 * Drives this phone's own adb daemon (Wireless debugging) with no PC. Used only by the client build: to
 * back up the game (the one way to reach its private asset packs), uninstall the Play copy and push the
 * game hook. The adb key is generated once and kept in files/adb, so pairing is a one-time step.
 */
object Adb {
    private const val SYNC_CHUNK = 64 * 1024
    private var manager: Manager? = null

    private fun manager(context: Context): Manager =
        manager ?: Manager(context.applicationContext).also { manager = it }

    /** Pair with Wireless debugging (host:port and the 6-digit code from the pairing dialog). One-time. */
    fun pair(context: Context, host: String, port: Int, code: String) {
        manager(context).pair(host, port, code)
    }

    /** Whether the Wireless debugging switch is on. Android 11+ keeps it in the global settings. */
    private fun wirelessDebuggingOn(context: Context) = try {
        Settings.Global.getInt(context.contentResolver, "adb_wifi_enabled") == 1
    } catch (_: Settings.SettingNotFoundException) {
        true // not readable on this phone: let discovery decide
    }

    /**
     * Connect to the daemon, discovering its TLS port over mDNS. Throws AdbPairingRequiredException if unpaired, and
     * its subclass WirelessDebuggingOff if the switch is off, which is how every phone starts (Android also turns it
     * off by itself when the Wi-Fi network changes). Without that check, discovery just times out.
     */
    fun connect(context: Context) {
        val m = manager(context)
        if (m.isConnected) return
        if (!wirelessDebuggingOn(context)) throw WirelessDebuggingOff()
        try {
            check(m.connectTls(context, TimeUnit.SECONDS.toMillis(30))) { "not connected" }
        } catch (e: AdbPairingRequiredException) {
            throw e
        } catch (e: Exception) {
            throw IOException("Couldn't reach this phone's Wireless debugging (${e.message}). Check that it is on and " +
                "that the phone is on Wi-Fi, then try again.", e)
        }
    }

    fun disconnect() {
        manager?.close()
        manager = null
    }

    /** Run a self-terminating shell command and return its combined output (don't use for streaming commands). */
    fun shell(context: Context, command: String): String =
        manager(context).openStream("shell:$command").use { it.openInputStream().readBytes().decodeToString() }

    /**
     * Stream `bu backup -noapk <pkg>` to [out]. The player must approve the backup on screen first, so this
     * blocks until they do. exec: gives a clean stdout (no stderr mixed in), so the .ab stream is intact.
     */
    fun backup(context: Context, pkg: String, out: File, onProgress: (Long) -> Unit) {
        manager(context).openStream("exec:bu backup -noapk $pkg").use { stream ->
            stream.openInputStream().use { input ->
                out.outputStream().use { file ->
                    val buffer = ByteArray(SYNC_CHUNK)
                    var total = 0L
                    while (true) {
                        val n = input.read(buffer)
                        if (n < 0) break
                        file.write(buffer, 0, n)
                        total += n
                        onProgress(total)
                    }
                }
            }
        }
    }

    fun uninstall(context: Context, pkg: String): Boolean =
        shell(context, "pm uninstall $pkg").contains("Success")

    /** Push [bytes] to [remotePath] over the sync service, which is binary-exact and confirms with OKAY. */
    fun push(context: Context, bytes: ByteArray, remotePath: String) {
        shell(context, "mkdir -p ${remotePath.substringBeforeLast('/')}")
        manager(context).openStream("sync:").use { stream ->
            val out = stream.openOutputStream()
            val header = "$remotePath,33188".encodeToByteArray() // 0o100644: a regular, world-readable file
            out.id("SEND", header.size)
            out.write(header)
            var off = 0
            while (off < bytes.size) {
                val n = minOf(SYNC_CHUNK, bytes.size - off)
                out.id("DATA", n)
                out.write(bytes, off, n)
                off += n
            }
            out.id("DONE", (System.currentTimeMillis() / 1000).toInt())
            out.flush()
            val reply = ByteArray(4)
            readFully(stream, reply)
            check(reply.decodeToString() == "OKAY") { "sync push to $remotePath failed" }
        }
    }

    /** A sync packet header: a 4-byte id and a little-endian 4-byte length (or mtime for DONE). */
    private fun OutputStream.id(id: String, value: Int) {
        write(id.encodeToByteArray())
        write(byteArrayOf(value.toByte(), (value shr 8).toByte(), (value shr 16).toByte(), (value shr 24).toByte()))
    }

    private fun readFully(stream: AdbStream, into: ByteArray) {
        val input = stream.openInputStream()
        var off = 0
        while (off < into.size) {
            val n = input.read(into, off, into.size - off)
            if (n < 0) throw java.io.EOFException("adb sync closed early")
            off += n
        }
    }

    private class Manager(context: Context) : AbsAdbConnectionManager() {
        private val key: PrivateKey
        private val cert: Certificate

        init {
            setApi(Build.VERSION.SDK_INT)
            try {
                Security.insertProviderAt(Conscrypt.newProvider(), 1) // TLS for pairing/connect on this device
            } catch (_: Throwable) {
            }
            val dir = File(context.filesDir, "adb").apply { mkdirs() }
            val keyFile = File(dir, "key.pk8")
            val certFile = File(dir, "cert.der")
            if (keyFile.isFile && certFile.isFile) {
                key = KeyFactory.getInstance("RSA").generatePrivate(PKCS8EncodedKeySpec(keyFile.readBytes()))
                cert = certFile.inputStream().use { CertificateFactory.getInstance("X.509").generateCertificate(it) }
            } else {
                val pair = KeyPairGenerator.getInstance("RSA").apply {
                    initialize(2048, SecureRandom.getInstance("SHA1PRNG"))
                }.generateKeyPair()
                key = pair.private
                cert = selfSigned(pair.public, key)
                keyFile.writeBytes(key.encoded)
                certFile.writeBytes(cert.encoded)
            }
        }

        override fun getPrivateKey() = key
        override fun getCertificate() = cert
        override fun getDeviceName() = "SlayerRevival"

        /** A self-signed certificate wrapping the adb public key, as adbd records for the paired key. */
        private fun selfSigned(publicKey: java.security.PublicKey, privateKey: PrivateKey): Certificate {
            val name = X500Name("CN=Slayer Revival")
            val from = Date()
            val to = Date(from.time + 10L * 365 * 24 * 60 * 60 * 1000) // 10 years; adbd only needs it to be valid
            val info = X509CertInfo()
            info.set("version", CertificateVersion(2))
            info.set("serialNumber", CertificateSerialNumber(Random().nextInt() and Int.MAX_VALUE))
            info.set("algorithmID", CertificateAlgorithmId(AlgorithmId.get("SHA512withRSA")))
            info.set("subject", CertificateSubjectName(name))
            info.set("key", CertificateX509Key(publicKey))
            info.set("validity", CertificateValidity(from, to))
            info.set("issuer", CertificateIssuerName(name))
            val extensions = CertificateExtensions()
            extensions.set("SubjectKeyIdentifier",
                SubjectKeyIdentifierExtension(KeyIdentifier(publicKey).identifier))
            extensions.set("PrivateKeyUsage", PrivateKeyUsageExtension(from, to))
            info.set("extensions", extensions)
            return X509CertImpl(info).apply { sign(privateKey, "SHA512withRSA") }
        }
    }
}
