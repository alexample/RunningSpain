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

/**
 * La app es la web de RunningSpain dentro de un WebView: los datos y cualquier mejora de la web
 * llegan solos, sin tener que instalar una APK nueva.
 * - Los enlaces de fuera (web oficial, reglamento, recorrido) se abren en el navegador.
 * - Deslizar hacia abajo recarga. Sin conexión se muestra la última versión guardada.
 */
public class MainActivity extends Activity {

    private static final String HOST = "alexample.github.io";
    private static final String START = "https://" + HOST + "/RunningSpain/";

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
            String u = web.getUrl();
            cargar(u != null && u.startsWith("https://" + HOST) ? u : START);
        });

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                Uri u = req.getUrl();
                if (HOST.equals(u.getHost()) && u.getPath() != null && u.getPath().startsWith("/RunningSpain")) {
                    return false;   // páginas de la propia web: dentro de la app
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

    /** Con conexión, pide siempre la web recién publicada (sin la copia guardada); sin conexión, la guardada. */
    private void cargar(String url) {
        if (hayConexion()) {
            java.util.Map<String, String> h = new java.util.HashMap<>();
            h.put("Cache-Control", "no-cache");
            h.put("Pragma", "no-cache");
            web.loadUrl(url, h);
        } else {
            web.loadUrl(url);
        }
    }

    /** Si la app se abre desde un enlace a la web (p. ej. …/RunningSpain/#nuevas), abre ese enlace. */
    private String urlInicial(Intent intent) {
        Uri data = intent != null ? intent.getData() : null;
        if (data != null && HOST.equals(data.getHost())) return data.toString();
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
