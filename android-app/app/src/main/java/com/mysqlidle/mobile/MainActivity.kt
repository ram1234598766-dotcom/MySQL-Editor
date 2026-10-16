package com.mysqlidle.mobile

import android.app.Activity
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.WindowInsets
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.webkit.SslErrorHandler
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.webkit.WebChromeClient
import android.net.http.SslCertificate
import android.net.http.SslError
import android.widget.Button
import java.io.ByteArrayInputStream
import java.security.MessageDigest
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ImageView
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast

class MainActivity : Activity() {
    private val prefs by lazy { getSharedPreferences("mysql_idle_mobile", MODE_PRIVATE) }
    private var root: LinearLayout? = null
    private var web: WebView? = null
    private var baseUri: Uri? = null
    private var pinnedFingerprint: String = ""
    private val blue = Color.rgb(37, 99, 235)
    private val ink = Color.rgb(15, 23, 42)
    private val muted = Color.rgb(100, 116, 139)
    private val paper = Color.rgb(248, 250, 252)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = paper
        window.navigationBarColor = paper
        window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR
        showConnectScreen()
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    private fun label(text: String, size: Float, color: Int = ink): TextView =
        TextView(this).apply {
            this.text = text
            textSize = size
            setTextColor(color)
        }

    private fun button(text: String, onClick: () -> Unit): Button =
        Button(this).apply {
            this.text = text
            isAllCaps = false
            setTextColor(Color.WHITE)
            backgroundTintList = android.content.res.ColorStateList.valueOf(blue)
            setOnClickListener { onClick() }
        }

    /**
     * Android 16 enforces edge-to-edge layouts for apps targeting API 36.
     * Keep interactive content inside the system-bar and display-cutout safe area.
     */
    @Suppress("DEPRECATION")
    private fun applySystemBarInsets(view: View) {
        val initialLeft = view.paddingLeft
        val initialTop = view.paddingTop
        val initialRight = view.paddingRight
        val initialBottom = view.paddingBottom

        view.setOnApplyWindowInsetsListener { target, insets ->
            val left: Int
            val top: Int
            val right: Int
            val bottom: Int
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                val safeInsets = insets.getInsets(
                    WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout()
                )
                left = safeInsets.left
                top = safeInsets.top
                right = safeInsets.right
                bottom = safeInsets.bottom
            } else {
                left = insets.systemWindowInsetLeft
                top = insets.systemWindowInsetTop
                right = insets.systemWindowInsetRight
                bottom = insets.systemWindowInsetBottom
            }
            target.setPadding(
                initialLeft + left,
                initialTop + top,
                initialRight + right,
                initialBottom + bottom
            )
            insets
        }
        view.requestApplyInsets()
    }

    private fun showConnectScreen(error: String? = null) {
        web?.stopLoading()
        web?.let { (it.parent as? ViewGroup)?.removeView(it); it.destroy() }
        web = null
        baseUri = null

        val scroll = ScrollView(this)
        applySystemBarInsets(scroll)
        val page = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(24), dp(28), dp(24), dp(28))
            setBackgroundColor(paper)
        }
        scroll.addView(page)
        setContentView(scroll)

        val brandHeader = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        brandHeader.addView(ImageView(this).apply {
            setImageResource(R.drawable.ic_mysqlidle_logo)
            contentDescription = "MySQL IDLE logo"
        }, LinearLayout.LayoutParams(dp(64), dp(64)))
        val brandText = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(14), 0, 0, 0)
        }
        brandText.addView(label("MySQL IDLE", 27f).apply {
            setTypeface(null, android.graphics.Typeface.BOLD)
        })
        brandText.addView(label("Mobile companion", 16f, blue).apply {
            setPadding(0, dp(2), 0, 0)
        })
        brandHeader.addView(brandText)
        page.addView(brandHeader, LinearLayout.LayoutParams(-1, -2).apply {
            bottomMargin = dp(28)
        })
        page.addView(label("Connect to the desktop companion", 19f).apply {
            setTypeface(null, android.graphics.Typeface.BOLD)
        })
        page.addView(label(
            "On the Windows desktop, open Tools → Android / Mobile Companion. Enter the HTTPS " +
                "address and the SHA-256 certificate fingerprint shown there. Compare every " +
                "fingerprint pair before connecting; the certificate changes when the companion restarts. " +
                "On the next screen, enter the same MySQL IDLE master password set on Windows plus the " +
                "temporary pairing code. A wrong password is rejected by the desktop.",
            14f, muted
        ).apply { setPadding(0, dp(8), 0, dp(18)) })

        page.addView(label("Desktop companion URL", 14f).apply {
            setTypeface(null, android.graphics.Typeface.BOLD)
        })
        val address = EditText(this).apply {
            hint = "https://192.168.1.20:8765"
            setSingleLine(true)
            inputType = android.text.InputType.TYPE_CLASS_TEXT or
                android.text.InputType.TYPE_TEXT_VARIATION_URI
            imeOptions = EditorInfo.IME_ACTION_GO
            setText(prefs.getString("server_url", ""))
            setPadding(dp(12), dp(10), dp(12), dp(10))
            setBackgroundColor(Color.WHITE)
        }
        page.addView(address, LinearLayout.LayoutParams(-1, dp(56)).apply {
            topMargin = dp(8)
            bottomMargin = dp(14)
        })
        page.addView(label("Desktop certificate SHA-256 fingerprint", 14f).apply {
            setTypeface(null, android.graphics.Typeface.BOLD)
        })
        val fingerprint = EditText(this).apply {
            hint = "AA:BB:CC:… (64 hex digits)"
            setSingleLine(true)
            inputType = android.text.InputType.TYPE_CLASS_TEXT or
                android.text.InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            imeOptions = EditorInfo.IME_ACTION_GO
            setText(pinnedFingerprint)
            setPadding(dp(12), dp(10), dp(12), dp(10))
            setBackgroundColor(Color.WHITE)
        }
        page.addView(fingerprint, LinearLayout.LayoutParams(-1, dp(56)).apply {
            topMargin = dp(8)
            bottomMargin = dp(10)
        })
        page.addView(label(
            "HTTPS is mandatory. Copy the fingerprint from the desktop window over a trusted channel; " +
                "do not accept an unexpected certificate or an error you cannot explain.",
            12f, muted
        ).apply { setPadding(0, 0, 0, dp(14)) })
        if (error != null) {
            page.addView(label(error, 14f, Color.rgb(185, 28, 28)).apply {
                setPadding(0, 0, 0, dp(10))
            })
        }
        page.addView(button("Verify and connect", onClick = {
            connect(address.text.toString(), fingerprint.text.toString())
        }), LinearLayout.LayoutParams(-1, dp(52)).apply { bottomMargin = dp(22) })

        page.addView(label("Network security", 16f).apply {
            setTypeface(null, android.graphics.Typeface.BOLD)
        })
        page.addView(label(
            "The app pins the desktop's HTTPS certificate using the SHA-256 fingerprint you provide. " +
                "Only private LAN IPv4 addresses are accepted. MySQL credentials are sent after pairing, " +
                "and are not saved by this app.",
            13f, muted
        ).apply { setPadding(0, dp(8), 0, dp(18)) })
        page.addView(label("Tip: allow the desktop application through your private-network firewall.",
            13f, muted))

        page.addView(label("Privacy Policy", 13f, blue).apply {
            setPadding(0, dp(14), 0, dp(2))
            setTypeface(null, android.graphics.Typeface.BOLD)
            paintFlags = paintFlags or android.graphics.Paint.UNDERLINE_TEXT_FLAG
            isClickable = true
            setOnClickListener {
                runCatching {
                    startActivity(
                        android.content.Intent(
                            android.content.Intent.ACTION_VIEW,
                            Uri.parse("https://github.com/ram1234598766-dotcom/MySQL-Editor/blob/main/PRIVACY_POLICY.md")
                        )
                    )
                }.onFailure {
                    Toast.makeText(this@MainActivity, "Could not open the privacy policy.", Toast.LENGTH_SHORT).show()
                }
            }
        })
    }

    private fun connect(raw: String, rawFingerprint: String) {
        val text = raw.trim().trimEnd('/')
        val parsed = runCatching { java.net.URI(text) }.getOrNull()
        val host = parsed?.host?.lowercase().orEmpty()
        val fingerprint = normalizeFingerprint(rawFingerprint)
        if (parsed == null || parsed.scheme?.lowercase() != "https" ||
            host.isBlank() || !isPrivateLanHost(host) || parsed.rawUserInfo != null ||
            parsed.rawPath !in listOf("", "/") || parsed.rawQuery != null ||
            parsed.rawFragment != null || parsed.port !in 1..65535) {
            showConnectScreen(
                "Enter an HTTPS root URL using a private LAN IPv4 address (for example, " +
                    "https://192.168.1.20:8765), without a path, query, fragment or username."
            )
            return
        }
        if (fingerprint == null) {
            showConnectScreen("Enter the complete 64-hex-digit SHA-256 certificate fingerprint from the desktop.")
            return
        }
        pinnedFingerprint = fingerprint
        baseUri = Uri.parse(parsed.toASCIIString())
        prefs.edit().putString("server_url", text).apply()
        showWebView(requireNotNull(baseUri))
    }

    private fun normalizeFingerprint(raw: String): String? {
        val compact = raw.trim().replace(Regex("[:\\-\\s]"), "")
        return compact.uppercase().takeIf { it.matches(Regex("^[0-9A-F]{64}$")) }
    }

    private fun isPrivateLanHost(host: String): Boolean {
        if (host == "localhost") return true
        val parts = host.split(".")
        if (parts.size != 4) return false
        val octets = parts.map { it.toIntOrNull() ?: return false }
        if (octets.any { it !in 0..255 }) return false
        val a = octets[0]
        val b = octets[1]
        return a == 10 || a == 127 || (a == 192 && b == 168) ||
            (a == 172 && b in 16..31) || (a == 169 && b == 254)
    }

    private fun certificateFingerprint(error: SslError): String? = runCatching {
        val certificate = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            error.certificate.x509Certificate
        } else {
            // SslCertificate exposes the encoded leaf in its saved state on older Android releases.
            val state = SslCertificate.saveState(error.certificate) ?: return null
            val bytes = state.getByteArray("x509-certificate") ?: return null
            CertificateFactory.getInstance("X.509")
                .generateCertificate(ByteArrayInputStream(bytes)) as X509Certificate
        } ?: return null
        MessageDigest.getInstance("SHA-256").digest(certificate.encoded)
            .joinToString("") { byte -> (byte.toInt() and 0xff).toString(16).padStart(2, '0').uppercase() }
    }.getOrNull()

    /**
     * A pinned self-signed desktop certificate may produce SSL_UNTRUSTED. Only that
     * error is acceptable: never proceed if Android also reports expiry, date,
     * hostname, or another certificate validation failure.
     *
     * Checking primaryError alone is insufficient because an SslError can contain
     * more than one certificate error.
     */
    private fun hasOnlyUntrustedCertificateError(error: SslError): Boolean {
        if (!error.hasError(SslError.SSL_UNTRUSTED)) return false

        val disallowedErrors = intArrayOf(
            SslError.SSL_NOTYETVALID,
            SslError.SSL_EXPIRED,
            SslError.SSL_IDMISMATCH,
            SslError.SSL_DATE_INVALID,
            SslError.SSL_INVALID
        )
        return disallowedErrors.none { error.hasError(it) }
    }

    private fun showWebView(uri: Uri) {
        val page = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(paper)
        }
        applySystemBarInsets(page)
        root = page

        val browser = WebView(this)
        web = browser

        val toolbar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(8), dp(4), dp(8), dp(4))
            setBackgroundColor(Color.WHITE)
        }
        toolbar.addView(ImageView(this).apply {
            setImageResource(R.drawable.ic_mysqlidle_logo)
            contentDescription = "MySQL IDLE logo"
        }, LinearLayout.LayoutParams(dp(34), dp(34)).apply {
            marginEnd = dp(6)
        })
        toolbar.addView(button("Server", onClick = { showConnectScreen() }),
            LinearLayout.LayoutParams(dp(78), dp(46)))
        toolbar.addView(label(uri.host ?: uri.toString(), 13f, muted).apply {
            maxLines = 1
            ellipsize = android.text.TextUtils.TruncateAt.END
            setPadding(dp(8), 0, dp(4), 0)
        }, LinearLayout.LayoutParams(0, -2, 1f))
        val refreshButton = button("Refresh") { browser.reload() }.apply {
            contentDescription = "Refresh desktop companion"
        }
        toolbar.addView(refreshButton, LinearLayout.LayoutParams(dp(82), dp(46)))
        page.addView(toolbar)

        val loadingBar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            max = 100
            progress = 0
            visibility = View.VISIBLE
            progressTintList = android.content.res.ColorStateList.valueOf(blue)
            contentDescription = "Page loading progress"
        }
        page.addView(loadingBar, LinearLayout.LayoutParams(-1, dp(3)))
        val loadingStatus = label("Connecting to desktop companion…", 12f, muted).apply {
            setPadding(dp(12), dp(6), dp(12), dp(6))
        }
        page.addView(loadingStatus, LinearLayout.LayoutParams(-1, -2))

        browser.setBackgroundColor(Color.WHITE)
        browser.settings.javaScriptEnabled = true
        browser.settings.domStorageEnabled = true
        browser.settings.allowFileAccess = false
        browser.settings.allowContentAccess = false
        browser.settings.javaScriptCanOpenWindowsAutomatically = false
        browser.settings.setSupportMultipleWindows(false)
        browser.settings.mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            browser.settings.safeBrowsingEnabled = true
        }
        var pageLoadFailed = false
        browser.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView, newProgress: Int) {
                loadingBar.progress = newProgress
                if (!pageLoadFailed && newProgress < 100) {
                    loadingBar.visibility = View.VISIBLE
                    loadingStatus.visibility = View.VISIBLE
                    loadingStatus.text = "Loading desktop companion… $newProgress%"
                } else if (!pageLoadFailed) {
                    loadingBar.visibility = View.GONE
                    loadingStatus.visibility = View.GONE
                }
            }
        }
        browser.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView, url: String?, favicon: android.graphics.Bitmap?) {
                pageLoadFailed = false
                loadingBar.progress = 0
                loadingBar.visibility = View.VISIBLE
                loadingStatus.text = "Connecting to desktop companion…"
                loadingStatus.visibility = View.VISIBLE
                refreshButton.isEnabled = false
            }

            override fun onPageFinished(view: WebView, url: String?) {
                refreshButton.isEnabled = true
                if (!pageLoadFailed) {
                    loadingBar.visibility = View.GONE
                    loadingStatus.visibility = View.GONE
                }
            }
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val target = request.url
                val base = baseUri
                if (base != null && target.scheme == base.scheme &&
                    target.host == base.host && target.port == base.port) {
                    return false
                }
                Toast.makeText(
                    this@MainActivity,
                    "Blocked navigation outside the verified desktop companion.",
                    Toast.LENGTH_SHORT
                ).show()
                return true
            }

            override fun onReceivedSslError(view: WebView, handler: SslErrorHandler, error: SslError) {
                val actualFingerprint = certificateFingerprint(error)
                val onlyUntrustedError = hasOnlyUntrustedCertificateError(error)
                val fingerprintMatches = actualFingerprint != null &&
                    actualFingerprint.equals(pinnedFingerprint, ignoreCase = true)
                if (onlyUntrustedError && fingerprintMatches) {
                    // This is the exact pinned desktop certificate, and Android reported
                    // no expiry, hostname, or date validation errors.
                    handler.proceed()
                    return
                }
                handler.cancel()
                pageLoadFailed = true
                loadingBar.visibility = View.GONE
                loadingStatus.text = if (actualFingerprint == null) {
                    "TLS certificate could not be inspected. Connection blocked."
                } else if (onlyUntrustedError && !fingerprintMatches) {
                    "TLS certificate fingerprint mismatch. Compare the complete fingerprint with the value displayed on the desktop; connection blocked."
                } else {
                    "TLS certificate validation failed (expiry, date, hostname, or another SSL error). Connection blocked."
                }
                loadingStatus.visibility = View.VISIBLE
                refreshButton.isEnabled = true
            }

            override fun onReceivedError(
                view: WebView,
                request: WebResourceRequest,
                error: android.webkit.WebResourceError
            ) {
                if (request.isForMainFrame) {
                    pageLoadFailed = true
                    loadingBar.visibility = View.GONE
                    loadingStatus.text = "Could not reach the desktop companion. Check Wi-Fi, address and firewall, then tap Refresh."
                    loadingStatus.visibility = View.VISIBLE
                    refreshButton.isEnabled = true
                }
            }
        }
        page.addView(browser, LinearLayout.LayoutParams(-1, 0, 1f))
        setContentView(page)
        browser.loadUrl(uri.toString())
    }

    @Suppress("DEPRECATION")
    override fun onBackPressed() {
        val current = web
        if (current != null && current.canGoBack()) current.goBack()
        else showConnectScreen()
    }

    override fun onDestroy() {
        web?.stopLoading()
        web?.destroy()
        web = null
        super.onDestroy()
    }
}
