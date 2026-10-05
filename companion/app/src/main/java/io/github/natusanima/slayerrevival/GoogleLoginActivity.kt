package io.github.natusanima.slayerrevival

import android.app.Activity
import android.os.Bundle
import android.view.View
import android.webkit.CookieManager
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.TextView
import kotlin.concurrent.thread

/**
 * Google's own sign-in page (the one Android shows when adding an account). Once it sets its one-time token the
 * app trades it for the account's token (PlayAccount); the player's password never reaches this app.
 */
class GoogleLoginActivity : Activity() {
    private companion object {
        const val PAGE = "https://accounts.google.com/EmbeddedSetup"
        // The page shows the account as <div data-profile-identifier data-email="...">.
        const val EMAIL = "(function() { var e = document.querySelector('[data-profile-identifier][data-email]'); " +
            "return e ? e.getAttribute('data-email') : null; })();"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val cookies = CookieManager.getInstance().apply { removeAllCookies(null) }
        val message = TextView(this).apply {
            textSize = 16f
            setPadding(48, 48, 48, 48)
            visibility = View.GONE
        }
        val web = WebView(this)
        cookies.setAcceptThirdPartyCookies(web, true)
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            safeBrowsingEnabled = false
        }
        web.webViewClient = object : WebViewClient() {
            private var taken = false

            override fun onPageFinished(view: WebView, url: String) {
                if (taken) return
                val token = cookies.getCookie(url)?.split(';')?.map { it.trim() }
                    ?.firstOrNull { it.startsWith("oauth_token=") }?.substringAfter('=') ?: return
                taken = true
                web.visibility = View.GONE
                message.visibility = View.VISIBLE
                message.text = "Signing in…"
                view.evaluateJavascript(EMAIL) { raw -> finishSignIn(message, raw.trim('"'), token) }
            }
        }
        setContentView(FrameLayout(this).apply {
            fitsSystemWindows = true
            addView(web)
            addView(message)
        })
        web.loadUrl(PAGE)
    }

    private fun finishSignIn(message: TextView, email: String, token: String) {
        thread(name = "play-sign-in") {
            val error = try {
                PlayAccount.signIn(this, email, token)
                null
            } catch (e: Exception) {
                PlayLog.write(this, "sign-in failed: $e")
                e.message ?: e.javaClass.simpleName
            }
            runOnUiThread {
                CookieManager.getInstance().removeAllCookies(null)
                if (error == null) finish() else message.text = "Signing in failed: $error\n\nGo back and try again."
            }
        }
    }
}
