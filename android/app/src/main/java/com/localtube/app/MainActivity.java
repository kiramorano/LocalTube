package com.localtube.app;

import android.Manifest;
import android.app.Activity;
import android.app.DownloadManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import java.net.HttpURLConnection;
import java.net.URL;

/**
 * Главный экран: WebView с интерфейсом LocalTube,
 * который обслуживается встроенным Python-сервером на 127.0.0.1:8000.
 */
public class MainActivity extends Activity {

    private static final String SERVER_URL = "http://127.0.0.1:8000/";
    private static final int FILE_CHOOSER_CODE = 100;

    private WebView webView;
    private ValueCallback<Uri[]> filePathCallback;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private boolean pageLoaded = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        if (Build.VERSION.SDK_INT >= 33 &&
                checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                        != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1);
        }

        ServerService.start(this);

        webView = findViewById(R.id.webview);
        setupWebView();
        waitForServer();
    }

    private void setupWebView() {
        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setAllowFileAccess(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);
        CookieManager.getInstance().setAcceptCookie(true);

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                if (url.startsWith("http://127.0.0.1") || url.startsWith("http://localhost")) {
                    return false;
                }
                // Внешние ссылки — в браузер
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                } catch (Exception ignored) {}
                return true;
            }
        });

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback,
                                             FileChooserParams params) {
                if (filePathCallback != null) filePathCallback.onReceiveValue(null);
                filePathCallback = callback;
                try {
                    startActivityForResult(params.createIntent(), FILE_CHOOSER_CODE);
                } catch (Exception e) {
                    filePathCallback = null;
                    return false;
                }
                return true;
            }
        });

        // Скачивание файлов из интерфейса (экспорт видео и т.д.)
        webView.setDownloadListener(new DownloadListener() {
            @Override
            public void onDownloadStart(String url, String userAgent, String contentDisposition,
                                        String mimeType, long contentLength) {
                try {
                    DownloadManager.Request req = new DownloadManager.Request(Uri.parse(url));
                    String fileName = URLUtil.guessFileName(url, contentDisposition, mimeType);
                    req.setNotificationVisibility(
                            DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                    req.setDestinationInExternalPublicDir(
                            Environment.DIRECTORY_DOWNLOADS, fileName);
                    DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
                    if (dm != null) {
                        dm.enqueue(req);
                        Toast.makeText(MainActivity.this,
                                "Скачивание: " + fileName, Toast.LENGTH_SHORT).show();
                    }
                } catch (Exception e) {
                    Toast.makeText(MainActivity.this,
                            "Ошибка скачивания", Toast.LENGTH_SHORT).show();
                }
            }
        });
    }

    /** Опрашивает сервер и загружает интерфейс, когда он поднимется. */
    private void waitForServer() {
        new Thread(() -> {
            for (int i = 0; i < 300; i++) {
                try {
                    HttpURLConnection conn =
                            (HttpURLConnection) new URL(SERVER_URL).openConnection();
                    conn.setConnectTimeout(1000);
                    conn.setReadTimeout(1000);
                    int code = conn.getResponseCode();
                    conn.disconnect();
                    if (code > 0) {
                        handler.post(this::loadApp);
                        return;
                    }
                } catch (Exception ignored) {}
                try { Thread.sleep(500); } catch (InterruptedException e) { return; }
            }
        }, "server-wait").start();
    }

    private void loadApp() {
        if (!pageLoaded) {
            pageLoaded = true;
            findViewById(R.id.loading_view).setVisibility(android.view.View.GONE);
            webView.setVisibility(android.view.View.VISIBLE);
            webView.loadUrl(SERVER_URL);
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == FILE_CHOOSER_CODE && filePathCallback != null) {
            Uri[] result = null;
            if (resultCode == RESULT_OK && data != null && data.getData() != null) {
                result = new Uri[]{data.getData()};
            }
            filePathCallback.onReceiveValue(result);
            filePathCallback = null;
        } else {
            super.onActivityResult(requestCode, resultCode, data);
        }
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            // Не убиваем сервер — просто сворачиваем приложение
            moveTaskToBack(true);
        }
    }
}
