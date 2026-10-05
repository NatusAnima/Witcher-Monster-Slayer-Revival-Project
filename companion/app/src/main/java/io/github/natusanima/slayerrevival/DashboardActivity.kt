package io.github.natusanima.slayerrevival

import android.app.Activity
import android.os.Bundle
import android.webkit.CookieManager
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import java.io.File

/**
 * The server's operator panel: players, map, news, tasks and weather. Its listener wants the operator key
 * with every request; this in-app browser holds it as a cookie, so other apps on the phone can't use the panel.
 */
class DashboardActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val key = File(filesDir, "state/admin/proxy.key").takeIf { it.isFile }?.readText()?.trim()
            ?: return finish() // the server writes it on its first start
        val url = "http://127.0.0.1:${ServerService.ADMIN_PORT}/"
        val web = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            webViewClient = WebViewClient()
        }
        setContentView(FrameLayout(this).apply {
            fitsSystemWindows = true
            addView(web)
        })
        CookieManager.getInstance().setCookie(url, "monster-admin-key=$key; HttpOnly; SameSite=Strict") { web.loadUrl(url) }
    }
}
