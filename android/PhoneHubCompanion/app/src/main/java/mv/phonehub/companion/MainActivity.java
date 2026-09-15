package mv.phonehub.companion;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;

public class MainActivity extends Activity {
    private static final int REQ_LOCATION = 44;
    private EditText pcIp;
    private TextView status;
    private SharedPreferences prefs;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences("phonehub", MODE_PRIVATE);
        buildUi();
        handleIntent(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleIntent(intent);
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(32, 42, 32, 32);
        root.setBackgroundColor(Color.rgb(11, 18, 32));

        TextView title = new TextView(this);
        title.setText("PhoneHub Companion");
        title.setTextSize(26);
        title.setTextColor(Color.WHITE);
        title.setGravity(Gravity.CENTER_HORIZONTAL);
        root.addView(title, new LinearLayout.LayoutParams(-1, -2));

        TextView help = new TextView(this);
        help.setText("Lightweight GPS sender for your PhoneHub PC. No Google Maps screen required.");
        help.setTextColor(Color.rgb(203, 213, 225));
        help.setTextSize(15);
        help.setPadding(0, 24, 0, 18);
        root.addView(help, new LinearLayout.LayoutParams(-1, -2));

        pcIp = new EditText(this);
        pcIp.setHint("PC Tailscale IP, example 100.125.11.48");
        pcIp.setSingleLine(true);
        pcIp.setTextColor(Color.WHITE);
        pcIp.setHintTextColor(Color.rgb(148, 163, 184));
        pcIp.setText(prefs.getString("pc_ip", "100.125.11.48"));
        root.addView(pcIp, new LinearLayout.LayoutParams(-1, -2));

        Button save = new Button(this);
        save.setText("Save PC IP");
        save.setOnClickListener(v -> {
            prefs.edit().putString("pc_ip", pcIp.getText().toString().trim()).apply();
            setStatus("PC IP saved.");
        });
        root.addView(save, new LinearLayout.LayoutParams(-1, -2));

        Button send = new Button(this);
        send.setText("Send Location Now");
        send.setOnClickListener(v -> sendLocation());
        root.addView(send, new LinearLayout.LayoutParams(-1, -2));

        status = new TextView(this);
        status.setTextColor(Color.rgb(251, 191, 36));
        status.setTextSize(15);
        status.setPadding(0, 24, 0, 0);
        root.addView(status, new LinearLayout.LayoutParams(-1, -2));

        setContentView(root, new ViewGroup.LayoutParams(-1, -1));
        setStatus("Ready. Allow location permission when asked.");
    }

    private void handleIntent(Intent intent) {
        if (intent == null) return;
        String incomingIp = intent.getStringExtra("pc_ip");
        if (incomingIp != null && incomingIp.trim().length() > 0) {
            pcIp.setText(incomingIp.trim());
            prefs.edit().putString("pc_ip", incomingIp.trim()).apply();
        }
        if (intent.getBooleanExtra("send_now", false)) {
            new Handler(Looper.getMainLooper()).postDelayed(this::sendLocation, 700);
        }
    }

    private void sendLocation() {
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION}, REQ_LOCATION);
            return;
        }

        setStatus("Getting GPS location...");
        LocationManager lm = (LocationManager) getSystemService(Context.LOCATION_SERVICE);
        Location best = null;
        try {
            Location gps = lm.getLastKnownLocation(LocationManager.GPS_PROVIDER);
            Location net = lm.getLastKnownLocation(LocationManager.NETWORK_PROVIDER);
            best = newer(gps, net);
        } catch (Exception ignored) {}

        if (best != null) {
            postLocation(best);
            return;
        }

        try {
            lm.requestSingleUpdate(LocationManager.NETWORK_PROVIDER, new LocationListener() {
                @Override public void onLocationChanged(Location location) { postLocation(location); }
                @Override public void onProviderEnabled(String provider) {}
                @Override public void onProviderDisabled(String provider) { setStatus("Location provider disabled."); }
            }, Looper.getMainLooper());
        } catch (Exception e) {
            setStatus("Cannot get location. Turn on Location/GPS.");
        }
    }

    private Location newer(Location a, Location b) {
        if (a == null) return b;
        if (b == null) return a;
        return a.getTime() >= b.getTime() ? a : b;
    }

    private void postLocation(Location loc) {
        final String ip = pcIp.getText().toString().trim();
        prefs.edit().putString("pc_ip", ip).apply();

        new Thread(() -> {
            try {
                String body = "device=" + enc(android.os.Build.MODEL)
                        + "&lat=" + enc(String.valueOf(loc.getLatitude()))
                        + "&lon=" + enc(String.valueOf(loc.getLongitude()))
                        + "&accuracy=" + enc(String.valueOf(loc.getAccuracy()))
                        + "&source=" + enc("android-companion");
                URL url = new URL("http://" + ip + ":8787/location");
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setConnectTimeout(8000);
                conn.setReadTimeout(8000);
                conn.setDoOutput(true);
                conn.setRequestProperty("Content-Type", "application/x-www-form-urlencoded");
                OutputStream os = conn.getOutputStream();
                os.write(body.getBytes("UTF-8"));
                os.close();
                int code = conn.getResponseCode();
                if (code >= 200 && code < 300) {
                    setStatus("Location sent to PhoneHub PC. Accuracy: " + Math.round(loc.getAccuracy()) + "m");
                } else {
                    setStatus("PC receiver error: " + code);
                }
            } catch (Exception e) {
                setStatus("Send failed. Check Tailscale and PC receiver.");
            }
        }).start();
    }

    private String enc(String v) throws Exception {
        return URLEncoder.encode(v == null ? "" : v, "UTF-8");
    }

    private void setStatus(String text) {
        runOnUiThread(() -> status.setText(text));
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQ_LOCATION && grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            sendLocation();
        } else {
            setStatus("Location permission is required.");
        }
    }
}
