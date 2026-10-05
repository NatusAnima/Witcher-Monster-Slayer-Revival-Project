package io.github.natusanima.slayerrevival

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.webkit.CookieManager
import android.webkit.WebStorage
import com.aurora.gplayapi.GooglePlayApi
import com.aurora.gplayapi.data.models.AuthData
import com.aurora.gplayapi.data.providers.DeviceInfoProvider
import com.aurora.gplayapi.helpers.AuthHelper
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.util.Locale
import java.util.Properties

/**
 * The player's Google account, kept only to ask Google Play for the game's extra data. Signing in follows Aurora
 * Store (GPL-3.0-or-later): the web sign-in's one-time token is traded for the account's long-lived token, then
 * gplayapi registers this phone with Google Play. Both stay in this app's private storage until [signOut].
 */
object PlayAccount {
    private const val AUTH = "https://android.clients.google.com/auth"
    private const val PLAY_SERVICES_SIGNATURE = "38918a453d07199354f8b19af05ec6562ced5788"

    private fun prefs(context: Context) = context.getSharedPreferences("play", Context.MODE_PRIVATE)

    /** The Pixel 9a profile gplayapi ships as a raw resource: the device this app registers with Google Play. */
    private fun profile(context: Context) = Properties().apply {
        val id = context.resources.getIdentifier("gplayapi_px_9a", "raw", context.packageName)
        context.resources.openRawResource(id).use { load(it) }
    }

    fun email(context: Context): String? = prefs(context).getString("email", null)

    fun signedIn(context: Context) = email(context) != null

    /** Trades the one-time token from Google's web sign-in for the account's token and registers this phone. */
    fun signIn(context: Context, email: String, oauthToken: String) {
        val locale = Locale.getDefault()
        val form = linkedMapOf(
            "lang" to locale.toString().replace('_', '-'),
            "google_play_services_version" to "19629032",
            "sdk_version" to "28",
            "device_country" to locale.country.lowercase(Locale.US),
            "Email" to email,
            "service" to "ac2dm",
            "get_accountid" to "1",
            "ACCESS_TOKEN" to "1",
            "callerPkg" to "com.google.android.gms",
            "add_account" to "1",
            "Token" to oauthToken,
            "callerSig" to PLAY_SERVICES_SIGNATURE,
            "droidguard_results" to "null",
        )
        val body = form.entries.joinToString("&") { "${it.key}=${URLEncoder.encode(it.value, "UTF-8")}" }
        val reply = post(AUTH, mapOf("app" to "com.google.android.gms", "User-Agent" to "",
            "Content-Type" to "application/x-www-form-urlencoded"), body.toByteArray())
        val answer = String(reply.body).lines().mapNotNull { line ->
            line.split('=', limit = 2).takeIf { it.size == 2 }?.let { it[0] to it[1] }
        }.toMap()
        val aas = answer["Token"] ?: throw IOException("Google did not accept the sign-in" +
            (answer["Error"]?.let { " ($it)" } ?: " (HTTP ${reply.code})"))
        val data = AuthHelper.build(email = answer["Email"]?.takeIf { it.isNotBlank() } ?: email, token = aas,
            tokenType = AuthHelper.Token.AAS, properties = profile(context), locale = locale)
        prefs(context).edit()
            .putString("email", data.email).putString("aas", aas).putString("gsf", data.gsfId)
            .putString("consistency", data.deviceCheckInConsistencyToken).putString("config", data.deviceConfigToken)
            .apply()
    }

    /** A session for Google Play with a fresh access token, on the device registration made at sign-in. */
    fun session(context: Context): AuthData {
        val p = prefs(context)
        val locale = Locale.getDefault()
        val saved = AuthData(
            email = p.getString("email", null) ?: throw IOException("Not signed in to Google"),
            aasToken = p.getString("aas", "")!!,
            gsfId = p.getString("gsf", "")!!,
            deviceCheckInConsistencyToken = p.getString("consistency", "")!!,
            deviceConfigToken = p.getString("config", "")!!,
            locale = locale,
            deviceInfoProvider = DeviceInfoProvider(profile(context), locale.toString()),
        )
        return saved.copy(authToken = GooglePlayApi().generateToken(saved, GooglePlayApi.Service.GOOGLE_PLAY))
    }

    /** Forgets the account here, and the web sign-in's cookies. It does not revoke anything at Google. */
    fun signOut(context: Context) {
        prefs(context).edit().clear().apply()
        Handler(Looper.getMainLooper()).post { // WebView objects belong to the main thread; the download signs out from its own
            try {
                CookieManager.getInstance().removeAllCookies(null)
                WebStorage.getInstance().deleteAllData()
            } catch (_: Exception) {
            }
        }
    }
}

class Reply(val code: Int, val body: ByteArray)

fun post(url: String, headers: Map<String, String>, body: ByteArray): Reply {
    val connection = URL(url).openConnection() as HttpURLConnection
    connection.requestMethod = "POST"
    connection.connectTimeout = 20_000
    connection.readTimeout = 60_000
    connection.doOutput = true
    headers.forEach { (name, value) -> connection.setRequestProperty(name, value) }
    try {
        connection.outputStream.use { it.write(body) }
        val code = connection.responseCode
        val stream = if (code < 400) connection.inputStream else connection.errorStream
        return Reply(code, stream?.use { it.readBytes() } ?: ByteArray(0))
    } finally {
        connection.disconnect()
    }
}
