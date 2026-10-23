package es.runningspain.app;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.provider.Settings;
import android.webkit.JavascriptInterface;
import android.content.res.Configuration;
import android.graphics.Color;
import android.net.ConnectivityManager;
import android.net.NetworkCapabilities;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;

import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsCompat;
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout;
import androidx.webkit.WebViewAssetLoader;
import android.webkit.WebResourceResponse;

/**
 * Las pantallas van dentro de la APK (assets/index.html), servidas desde https://appassets.androidplatform.net/assets/.
 * La app solo descarga los datos (carreras.json); sin conexión usa los últimos descargados.
 * - Los enlaces de fuera (web oficial, reglamento, recorrido) se abren en el navegador.
 * - Los enlaces a la web de RunningSpain (…/#c-id, …/c/id.html, …/#nuevas) se abren dentro de la app.
 * - Deslizar hacia abajo recarga los datos.
 */
public class MainActivity extends Activity {

    private static final String HOST = "alexample.github.io";          // la web (enlaces compartidos)
    private static final String LOCAL = "appassets.androidplatform.net";
    private static final String START = "https://" + LOCAL + "/assets/index.html";

    private WebView web;
    private SwipeRefreshLayout refresh;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        boolean dark = (getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK)
                == Configuration.UI_MODE_NIGHT_YES;
        int fondo = Color.parseColor(dark ? "#121417" : "#EEF0F2");

        WindowCompat.setDecorFitsSystemWindows(getWindow(), false);
        getWindow().setStatusBarColor(Color.TRANSPARENT);
        getWindow().setNavigationBarColor(Color.TRANSPARENT);
        WindowCompat.getInsetsController(getWindow(), getWindow().getDecorView())
                .setAppearanceLightStatusBars(!dark);
        WindowCompat.getInsetsController(getWindow(), getWindow().getDecorView())
                .setAppearanceLightNavigationBars(!dark);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(fondo);
        refresh = new SwipeRefreshLayout(this);
        refresh.setColorSchemeColors(Color.parseColor("#E0461C"));
        web = new WebView(this);
        web.setBackgroundColor(fondo);
        refresh.addView(web, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        root.addView(refresh, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        setContentView(root);

        // Deja libres la barra de estado y la de navegación.
        ViewCompat.setOnApplyWindowInsetsListener(root, (v, insets) -> {
            Insets bars = insets.getInsets(WindowInsetsCompat.Type.systemBars()
                    | WindowInsetsCompat.Type.displayCutout());
            Insets teclado = insets.getInsets(WindowInsetsCompat.Type.ime());
            v.setPadding(bars.left, bars.top, bars.right, Math.max(bars.bottom, teclado.bottom));
            return WindowInsetsCompat.CONSUMED;
        });

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setCacheMode(hayConexion() ? WebSettings.LOAD_DEFAULT : WebSettings.LOAD_CACHE_ELSE_NETWORK);

        // Solo se recarga al deslizar si la página está arriba del todo.
        refresh.setOnChildScrollUpCallback((parent, child) -> web.getScrollY() > 0);
        refresh.setOnRefreshListener(() -> {
            web.getSettings().setCacheMode(hayConexion() ? WebSettings.LOAD_DEFAULT : WebSettings.LOAD_CACHE_ELSE_NETWORK);
            web.reload();   // vuelve a descargar los datos
        });

        final WebViewAssetLoader loader = new WebViewAssetLoader.Builder()
                .setDomain(LOCAL)
                .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this))
                .build();

        web.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest req) {
                return loader.shouldInterceptRequest(req.getUrl());
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                Uri u = req.getUrl();
                if (LOCAL.equals(u.getHost())) return false;                       // pantallas de la app
                if (HOST.equals(u.getHost()) && u.getPath() != null && u.getPath().startsWith("/RunningSpain")) {
                    view.loadUrl(local(u));                                          // enlace a la web: dentro de la app
                    return true;
                }
                try { startActivity(new Intent(Intent.ACTION_VIEW, u)); } catch (Exception ignored) { }
                return true;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                refresh.setRefreshing(false);
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
                if (!req.isForMainFrame()) return;
                refresh.setRefreshing(false);
                // Sin conexión y sin copia guardada: aviso sencillo.
                String html = "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'></head>"
                        + "<body style='font-family:sans-serif;padding:40px 24px;text-align:center;"
                        + (dark ? "background:#121417;color:#eef1f4" : "background:#eef0f2;color:#16191d") + "'>"
                        + "<h2>Sin conexión</h2><p>No se ha podido cargar el calendario.</p>"
                        + "<p>Desliza hacia abajo para volver a intentarlo.</p></body></html>";
                view.loadDataWithBaseURL(START, html, "text/html", "utf-8", START);
            }
        });

        // Avisos de carreras nuevas: la página guarda los filtros con AndroidApp.guardarAjustes(json).
        web.addJavascriptInterface(new Puente(), "AndroidApp");
        AvisosWorker.crearCanal(this);
        AvisosWorker.programar(this);

        if (savedInstanceState != null) {
            web.restoreState(savedInstanceState);
        } else {
            cargar(urlInicial(getIntent()));
        }
    }

    private void cargar(String url) {
        web.loadUrl(url);
    }

    /** Si la app se abre desde un enlace a la web (p. ej. …/RunningSpain/#nuevas), abre esa pantalla. */
    private String urlInicial(Intent intent) {
        Uri data = intent != null ? intent.getData() : null;
        if (data != null && HOST.equals(data.getHost())) return local(data);
        return START;
    }

    /** …/RunningSpain/#c-id, …/RunningSpain/c/id.html o …/#nuevas → la misma pantalla dentro de la app. */
    private static String local(Uri u) {
        String frag = u.getFragment();
        if (frag != null && !frag.isEmpty()) return START + "#" + frag;
        String path = u.getPath() == null ? "" : u.getPath();
        java.util.regex.Matcher m = java.util.regex.Pattern.compile("/c/([a-z0-9-]+)\\.html$").matcher(path);
        if (m.find()) return START + "#c-" + m.group(1);
        return START;
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        if (intent.getData() != null) cargar(urlInicial(intent));
    }

    private boolean hayConexion() {
        ConnectivityManager cm = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
        if (cm == null) return true;
        NetworkCapabilities nc = cm.getNetworkCapabilities(cm.getActiveNetwork());
        return nc != null && nc.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET);
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    @Override
    protected void onPause() {
        super.onPause();
        web.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        web.onResume();
        AvisosWorker.revisarYa(this);
        // por si se acaba de dar o quitar el permiso de notificaciones en los ajustes de Android
        web.evaluateJavascript("window.alVolverApp && window.alVolverApp()", null);
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] res) {
        super.onRequestPermissionsResult(code, perms, res);
        web.evaluateJavascript("window.alVolverApp && window.alVolverApp()", null);
    }

    /** Lo que la página puede pedir a Android: leer y guardar los filtros de avisos y el permiso. */
    private class Puente {
        @JavascriptInterface
        public String leerAjustes() {
            return getSharedPreferences(AvisosWorker.PREFS, Context.MODE_PRIVATE).getString("ajustes", "{}");
        }

        @JavascriptInterface
        public void guardarAjustes(String json) {
            getSharedPreferences(AvisosWorker.PREFS, Context.MODE_PRIVATE).edit().putString("ajustes", json).apply();
            AvisosWorker.revisarYa(MainActivity.this);
        }

        /** Versión instalada (para avisar si hay una más nueva). */
        @JavascriptInterface
        public String version() {
            try { return getPackageManager().getPackageInfo(getPackageName(), 0).versionName; } catch (Exception e) { return ""; }
        }

        /** «Compartir»: abre el menú de compartir de Android (WhatsApp, Telegram…) con el texto de la carrera. */
        @JavascriptInterface
        public void compartir(final String texto) {
            runOnUiThread(() -> {
                Intent i = new Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, texto);
                try { startActivity(Intent.createChooser(i, "Compartir carrera")); } catch (Exception ignored) { }
            });
        }

        /** Carreras favoritas (lista de ids en JSON), para los recordatorios. */
        @JavascriptInterface
        public String leerFavs() {
            return getSharedPreferences(AvisosWorker.PREFS, Context.MODE_PRIVATE).getString("favs", "[]");
        }

        @JavascriptInterface
        public void guardarFavs(String json) {
            getSharedPreferences(AvisosWorker.PREFS, Context.MODE_PRIVATE).edit().putString("favs", json).apply();
            AvisosWorker.revisarYa(MainActivity.this);
            permisoAvisos();   // la primera favorita: pedir permiso de notificaciones si hace falta
        }

        @JavascriptInterface
        public boolean avisosActivos() {
            return AvisosWorker.puedeNotificar(MainActivity.this);
        }

        /** Pide permiso de notificaciones (Android 13 o superior). */
        @JavascriptInterface
        public void permisoAvisos() {
            if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                    != PackageManager.PERMISSION_GRANTED) {
                runOnUiThread(() -> requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 7));
            }
        }

        /** Abre los ajustes de notificaciones de la app (si el permiso se denegó antes). */
        @JavascriptInterface
        public void abrirAjustesAvisos() {
            runOnUiThread(() -> {
                try {
                    Intent i = new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                            .putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName());
                    startActivity(i);
                } catch (Exception ignored) { }
            });
        }
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }
}
