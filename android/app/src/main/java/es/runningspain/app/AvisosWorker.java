package es.runningspain.app;

import android.Manifest;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;

import androidx.annotation.NonNull;
import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;
import androidx.core.content.ContextCompat;
import androidx.work.Constraints;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.TimeZone;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Revisa el calendario en segundo plano y avisa de las carreras NUEVAS que encajan con
 * los filtros elegidos en la app (distancias y comunidades).
 *
 * Preferencias ("avisos"):
 *   ajustes = {"activo":bool, "dist":["42","21","10","5","x"], "regiones":["Andalucía",…],   (lista vacía = todas)
 *              "fecha":{"modo":"dias","dias":30} | {"modo":"rango","desde":"AAAA-MM-DD","hasta":"AAAA-MM-DD"} | {},
 *              "aperturas":bool}   (avisar también cuando una carrera que encaja abre inscripciones)
 *   insc    = {id: estado de inscripción de la última revisión}
 *   vistas  = ids de carreras ya conocidas (nunca se avisa dos veces de la misma)
 * La primera revisión solo memoriza lo que ya existe, para no llenar el móvil de avisos.
 */
public class AvisosWorker extends Worker {

    static final String PREFS = "avisos";
    static final String CANAL = "carreras_nuevas";
    static final String URL_DATOS = "https://alexample.github.io/RunningSpain/data/carreras.json";
    private static final String TRABAJO = "revisar-carreras";
    private static final Pattern KM = Pattern.compile("(\\d+(?:[.,]\\d+)?)\\s*km", Pattern.CASE_INSENSITIVE);

    public AvisosWorker(@NonNull Context c, @NonNull WorkerParameters p) { super(c, p); }

    /** Revisión periódica cada 3 horas (Android puede retrasarla un poco para ahorrar batería). */
    static void programar(Context c) {
        Constraints red = new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build();
        PeriodicWorkRequest req = new PeriodicWorkRequest.Builder(AvisosWorker.class, 3, TimeUnit.HOURS)
                .setConstraints(red).build();
        WorkManager.getInstance(c).enqueueUniquePeriodicWork(TRABAJO, ExistingPeriodicWorkPolicy.UPDATE, req);
    }

    /** Revisión inmediata (al abrir la app o al cambiar los filtros). */
    static void revisarYa(Context c) {
        Constraints red = new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build();
        OneTimeWorkRequest req = new OneTimeWorkRequest.Builder(AvisosWorker.class).setConstraints(red).build();
        WorkManager.getInstance(c).enqueueUniqueWork(TRABAJO + "-ya", ExistingWorkPolicy.REPLACE, req);
    }

    static void crearCanal(Context c) {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel ch = new NotificationChannel(CANAL, "Carreras nuevas",
                    NotificationManager.IMPORTANCE_DEFAULT);
            ch.setDescription("Aviso cuando aparece una carrera nueva de las distancias y comunidades que elijas.");
            NotificationManager nm = c.getSystemService(NotificationManager.class);
            if (nm != null) nm.createNotificationChannel(ch);
        }
    }

    static boolean puedeNotificar(Context c) {
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(c, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) return false;
        return NotificationManagerCompat.from(c).areNotificationsEnabled();
    }

    @NonNull
    @Override
    public Result doWork() {
        Context c = getApplicationContext();
        SharedPreferences p = c.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        JSONObject aj;
        try { aj = new JSONObject(p.getString("ajustes", "{}")); } catch (Exception e) { aj = new JSONObject(); }
        boolean activo = aj.optBoolean("activo", false);
        Set<String> dist = conjunto(aj.optJSONArray("dist"));
        Set<String> regiones = conjunto(aj.optJSONArray("regiones"));
        // Fecha de la carrera: próximos N días o entre dos fechas (vacío = cualquiera)
        JSONObject fe = aj.optJSONObject("fecha");
        String fDesde = "", fHasta = "";
        if (fe != null) {
            if ("dias".equals(fe.optString("modo")) && fe.optInt("dias", 0) > 0) {
                fHasta = new SimpleDateFormat("yyyy-MM-dd", Locale.ROOT)
                        .format(new Date(System.currentTimeMillis() + fe.optInt("dias") * 86400000L));
            } else if ("rango".equals(fe.optString("modo"))) {
                fDesde = fe.optString("desde", "");
                fHasta = fe.optString("hasta", "");
            }
        }

        String cuerpo;
        try { cuerpo = descargar(URL_DATOS); } catch (Exception e) { return Result.retry(); }
        JSONArray carreras;
        try { carreras = new JSONObject(cuerpo).getJSONArray("races"); } catch (Exception e) { return Result.success(); }

        Set<String> vistas = new HashSet<>(p.getStringSet("vistas", new HashSet<>()));
        boolean aperturas = aj.optBoolean("aperturas", false);
        JSONObject inscAntes;
        try { inscAntes = new JSONObject(p.getString("insc", "{}")); } catch (Exception e) { inscAntes = new JSONObject(); }
        JSONObject inscAhora = new JSONObject();
        List<JSONObject> abiertas = new ArrayList<>();
        boolean primera = !p.getBoolean("iniciado", false);
        String hoy = new SimpleDateFormat("yyyy-MM-dd", Locale.ROOT).format(new Date());
        List<JSONObject> nuevas = new ArrayList<>();
        Set<String> ahora = new HashSet<>();

        for (int i = 0; i < carreras.length(); i++) {
            JSONObject r = carreras.optJSONObject(i);
            if (r == null) continue;
            String id = r.optString("id");
            ahora.add(id);
            String st = r.optString("inscripcion", "");
            try { if (!st.isEmpty()) inscAhora.put(id, st); } catch (Exception ignored) { }
            String antes = inscAntes.optString(id, "");
            boolean seAbre = "abierta".equals(st) && ("proximamente".equals(antes) || "cerrada".equals(antes));
            if (seAbre && aperturas && !primera && encajaFiltros(r, hoy, fDesde, fHasta, regiones, dist)) abiertas.add(r);
            if (vistas.contains(id) || primera || !activo) continue;
            if (r.optString("date").compareTo(hoy) < 0) continue;
            String fecha = r.optString("date");
            if (!fDesde.isEmpty() && fecha.compareTo(fDesde) < 0) continue;
            if (!fHasta.isEmpty() && fecha.compareTo(fHasta) > 0) continue;
            if (!regiones.isEmpty() && !regiones.contains(r.optString("region"))) continue;
            if (!dist.isEmpty() && !encaja(categorias(r), dist)) continue;
            nuevas.add(r);
        }
        // Se recuerdan todas las actuales (encajen o no), así cambiar los filtros no trae avisos atrasados.
        p.edit().putStringSet("vistas", ahora).putBoolean("iniciado", true).putString("insc", inscAhora.toString()).apply();
        if (!abiertas.isEmpty() && puedeNotificar(c)) {
            crearCanal(c);
            for (JSONObject r : abiertas) notificarApertura(c, r);
        }

        if (!nuevas.isEmpty() && puedeNotificar(c)) {
            crearCanal(c);
            nuevas.sort((a, b) -> a.optString("date").compareTo(b.optString("date")));
            if (nuevas.size() <= 3) for (JSONObject r : nuevas) notificarUna(c, r);
            else notificarResumen(c, nuevas);
        }
        return Result.success();
    }

    // ------------------------------------------------------------- filtros
    private static boolean encajaFiltros(JSONObject r, String hoy, String fDesde, String fHasta,
                                         Set<String> regiones, Set<String> dist) {
        String fecha = r.optString("date");
        if (fecha.compareTo(hoy) < 0) return false;
        if (!fDesde.isEmpty() && fecha.compareTo(fDesde) < 0) return false;
        if (!fHasta.isEmpty() && fecha.compareTo(fHasta) > 0) return false;
        if (!regiones.isEmpty() && !regiones.contains(r.optString("region"))) return false;
        return dist.isEmpty() || encaja(categorias(r), dist);
    }
    private static Set<String> conjunto(JSONArray a) {
        Set<String> s = new HashSet<>();
        if (a != null) for (int i = 0; i < a.length(); i++) s.add(a.optString(i));
        return s;
    }

    private static boolean encaja(Set<String> cats, Set<String> dist) {
        for (String k : cats) if (dist.contains(k)) return true;
        return false;
    }

    /** Distancias de la carrera: de los km de la ficha si los hay (igual que la web); si no, de sus etiquetas. */
    static Set<String> categorias(JSONObject r) {
        List<String> tags = new ArrayList<>();
        Matcher m = KM.matcher(r.optString("km", ""));
        while (m.find()) {
            double v = Double.parseDouble(m.group(1).replace(',', '.'));
            tags.add(v >= 42 && v <= 42.4 ? "42K" : v >= 21 && v <= 21.2 ? "21K" : Math.round(v) + "K");
        }
        if (tags.isEmpty()) {
            JSONArray d = r.optJSONArray("distances");
            if (d != null) for (int i = 0; i < d.length(); i++) tags.add(d.optString(i));
        }
        Set<String> out = new HashSet<>();
        for (String t : tags) {
            if (t.startsWith("42")) out.add("42");
            else if (t.startsWith("21") || t.startsWith("20")) out.add("21");
            else if (t.equals("10K")) out.add("10");
            else if (t.equals("5K")) out.add("5");
            else out.add("x");
        }
        if (out.isEmpty()) out.add("x");
        return out;
    }

    // ------------------------------------------------------------- avisos
    private static String cuando(JSONObject r) {
        try {
            Date d = new SimpleDateFormat("yyyy-MM-dd", Locale.ROOT).parse(r.optString("date"));
            SimpleDateFormat f = new SimpleDateFormat("EEE d MMM", new Locale("es", "ES"));
            f.setTimeZone(TimeZone.getDefault());
            String t = r.optString("time", "");
            return f.format(d) + (t.isEmpty() ? "" : " · " + t + " h");
        } catch (Exception e) {
            return r.optString("date");
        }
    }

    private static String lugar(JSONObject r) {
        String city = r.optString("city", ""), reg = r.optString("region", "");
        if (city.isEmpty()) return reg;
        return reg.isEmpty() ? city : city + " (" + reg + ")";
    }

    private static PendingIntent abrirNuevas(Context c, int codigo) {
        Intent abrir = new Intent(Intent.ACTION_VIEW, Uri.parse("https://alexample.github.io/RunningSpain/#nuevas"), c, MainActivity.class)
                .setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        return PendingIntent.getActivity(c, codigo, abrir, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    private static void notificarUna(Context c, JSONObject r) {
        int id = r.optString("id").hashCode();
        String texto = cuando(r) + " · " + lugar(r);
        String km = r.optString("km", "");
        NotificationCompat.Builder n = new NotificationCompat.Builder(c, CANAL)
                .setSmallIcon(R.drawable.ic_aviso)
                .setColor(0xFFC60B1E)
                .setContentTitle("🏃 " + r.optString("name"))
                .setContentText(texto)
                .setStyle(new NotificationCompat.BigTextStyle().bigText(texto + (km.isEmpty() ? "" : "\n" + km)))
                .setContentIntent(abrirNuevas(c, id))
                .setAutoCancel(true);
        try { NotificationManagerCompat.from(c).notify(id, n.build()); } catch (SecurityException ignored) { }
    }

    private static void notificarApertura(Context c, JSONObject r) {
        int id = ("ins" + r.optString("id")).hashCode();
        NotificationCompat.Builder n = new NotificationCompat.Builder(c, CANAL)
                .setSmallIcon(R.drawable.ic_aviso)
                .setColor(0xFF13805A)
                .setContentTitle("🟢 Inscripciones abiertas: " + r.optString("name"))
                .setContentText(cuando(r) + " · " + lugar(r))
                .setContentIntent(abrirNuevas(c, id))
                .setAutoCancel(true);
        String url = r.optString("url", "");
        if (r.optBoolean("official") && !url.isEmpty()) {   // tocar lleva directamente a inscribirse
            Intent web = new Intent(Intent.ACTION_VIEW, Uri.parse(url)).setFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            n.setContentIntent(PendingIntent.getActivity(c, id, web, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE));
        }
        try { NotificationManagerCompat.from(c).notify(id, n.build()); } catch (SecurityException ignored) { }
    }

    private static void notificarResumen(Context c, List<JSONObject> rs) {
        NotificationCompat.InboxStyle st = new NotificationCompat.InboxStyle();
        for (int i = 0; i < Math.min(6, rs.size()); i++) {
            JSONObject r = rs.get(i);
            st.addLine(cuando(r) + " · " + r.optString("name"));
        }
        if (rs.size() > 6) st.setSummaryText("y " + (rs.size() - 6) + " más");
        NotificationCompat.Builder n = new NotificationCompat.Builder(c, CANAL)
                .setSmallIcon(R.drawable.ic_aviso)
                .setColor(0xFFC60B1E)
                .setContentTitle("🏃 " + rs.size() + " carreras nuevas para ti")
                .setContentText("Toca para verlas en RunningSpain")
                .setStyle(st)
                .setNumber(rs.size())
                .setContentIntent(abrirNuevas(c, 1))
                .setAutoCancel(true);
        try { NotificationManagerCompat.from(c).notify(1, n.build()); } catch (SecurityException ignored) { }
    }

    private static String descargar(String url) throws Exception {
        HttpURLConnection con = (HttpURLConnection) new URL(url + "?t=" + System.currentTimeMillis() / 600000).openConnection();
        con.setConnectTimeout(15000);
        con.setReadTimeout(20000);
        con.setUseCaches(false);
        int code = con.getResponseCode();
        if (code != 200) throw new Exception("HTTP " + code);
        try (InputStream in = con.getInputStream(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buf = new byte[16384];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            return out.toString("UTF-8");
        } finally {
            con.disconnect();
        }
    }
}
