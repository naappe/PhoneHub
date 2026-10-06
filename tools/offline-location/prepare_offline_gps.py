#!/usr/bin/env python3
"""
Patch the existing AndroidBridge Companion project with offline GNSS history.

Expected local project:
    C:\\Project-Archive\\AndroidBridge-Calls

The update keeps GPS acquisition local to the phone. No Internet is needed to
create fixes. Pending fixes are sent to the PC only when the Tailscale route is
reachable again.
"""
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

PROJECT = Path(r"C:\Project-Archive\AndroidBridge-Calls")
PC_TAILSCALE_IP = "100.113.209.27"
PC_PORT = 5571
PACKAGE = "com.androidbridge"
ANDROID_NS = "http://schemas.android.com/apk/res/android"
A = "{" + ANDROID_NS + "}"
ET.register_namespace("android", ANDROID_NS)

JAVA_DIR = PROJECT / "app" / "src" / "main" / "java" / "com" / "androidbridge"
MANIFEST = PROJECT / "app" / "src" / "main" / "AndroidManifest.xml"

SERVICE = r'''package com.androidbridge;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Build;
import android.os.Bundle;
import android.os.IBinder;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.FileReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;

public class OfflineLocationService extends Service implements LocationListener {
    private static final String CHANNEL = "androidbridge_offline_gps";
    private static final int NOTIFICATION_ID = 5571;
    private static final long MIN_TIME_MS = 60_000L;
    private static final float MIN_DISTANCE_M = 25f;
    private static final String PC_IP = "__PC_IP__";
    private static final int PC_PORT = __PC_PORT__;

    private LocationManager locationManager;
    private final Object fileLock = new Object();
    private volatile boolean syncRunning = false;

    @Override
    public void onCreate() {
        super.onCreate();
        createChannel();
        Notification notification = buildNotification("Offline GPS logging active");
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(
                    NOTIFICATION_ID,
                    notification,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION
            );
        } else {
            startForeground(NOTIFICATION_ID, notification);
        }
        startGps();
        flushPendingAsync();
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL,
                    "AndroidBridge Offline GPS",
                    NotificationManager.IMPORTANCE_LOW
            );
            channel.setDescription("Stores GPS fixes locally while the phone is offline.");
            getSystemService(NotificationManager.class).createNotificationChannel(channel);
        }
    }

    private Notification buildNotification(String text) {
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL)
                : new Notification.Builder(this);
        return b.setContentTitle("AndroidBridge")
                .setContentText(text)
                .setSmallIcon(android.R.drawable.ic_menu_mylocation)
                .setOngoing(true)
                .build();
    }

    private void startGps() {
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)
                != PackageManager.PERMISSION_GRANTED) {
            stopSelf();
            return;
        }

        locationManager = (LocationManager) getSystemService(LOCATION_SERVICE);
        try {
            locationManager.requestLocationUpdates(
                    LocationManager.GPS_PROVIDER,
                    MIN_TIME_MS,
                    MIN_DISTANCE_M,
                    this
            );

            Location last = locationManager.getLastKnownLocation(LocationManager.GPS_PROVIDER);
            if (last != null) {
                saveLocation(last, "gps_last_known");
            }
        } catch (Exception ignored) {
        }
    }

    @Override
    public void onLocationChanged(Location location) {
        saveLocation(location, "gps");
    }

    @Override
    public void onProviderEnabled(String provider) {
    }

    @Override
    public void onProviderDisabled(String provider) {
    }

    @Override
    public void onStatusChanged(String provider, int status, Bundle extras) {
    }

    private void saveLocation(Location location, String source) {
        try {
            JSONObject o = new JSONObject();
            o.put("latitude", location.getLatitude());
            o.put("longitude", location.getLongitude());
            o.put("accuracy_m", location.hasAccuracy() ? location.getAccuracy() : JSONObject.NULL);
            o.put("altitude_m", location.hasAltitude() ? location.getAltitude() : JSONObject.NULL);
            o.put("speed_mps", location.hasSpeed() ? location.getSpeed() : JSONObject.NULL);
            o.put("bearing_deg", location.hasBearing() ? location.getBearing() : JSONObject.NULL);
            o.put("fix_time_ms", location.getTime());
            o.put("saved_time_ms", System.currentTimeMillis());
            o.put("provider", location.getProvider());
            o.put("source", source);
            o.put("offline_capable", true);

            String line = o.toString() + "\n";

            synchronized (fileLock) {
                append(new File(getFilesDir(), "offline_location_history.jsonl"), line);
                append(new File(getFilesDir(), "offline_location_pending.jsonl"), line);
            }

            flushPendingAsync();
        } catch (Exception ignored) {
        }
    }

    private void append(File file, String text) throws Exception {
        try (FileOutputStream out = new FileOutputStream(file, true)) {
            out.write(text.getBytes(StandardCharsets.UTF_8));
            out.flush();
        }
    }

    private void flushPendingAsync() {
        if (syncRunning) return;
        syncRunning = true;
        new Thread(() -> {
            try {
                flushPending();
            } finally {
                syncRunning = false;
            }
        }, "AndroidBridge-GPS-Sync").start();
    }

    private void flushPending() {
        File pending = new File(getFilesDir(), "offline_location_pending.jsonl");
        StringBuilder payload = new StringBuilder();

        synchronized (fileLock) {
            if (!pending.exists() || pending.length() == 0) return;
            try (BufferedReader r = new BufferedReader(new FileReader(pending))) {
                String line;
                while ((line = r.readLine()) != null) {
                    if (!line.trim().isEmpty()) payload.append(line).append('\n');
                }
            } catch (Exception e) {
                return;
            }
        }

        if (payload.length() == 0) return;

        try (Socket socket = new Socket()) {
            socket.connect(new InetSocketAddress(PC_IP, PC_PORT), 2500);
            socket.setSoTimeout(5000);

            OutputStream out = socket.getOutputStream();
            out.write(payload.toString().getBytes(StandardCharsets.UTF_8));
            out.flush();
            socket.shutdownOutput();

            BufferedReader response = new BufferedReader(
                    new InputStreamReader(socket.getInputStream(), StandardCharsets.UTF_8)
            );
            String ack = response.readLine();

            if (ack != null && ack.startsWith("ACK ")) {
                int accepted = Integer.parseInt(ack.substring(4).trim());
                int sent = payload.toString().split("\n").length;
                if (accepted == sent) {
                    synchronized (fileLock) {
                        new FileOutputStream(pending, false).close();
                    }
                    updateNotification("GPS history synced to AndroidBridge PC");
                }
            }
        } catch (Exception ignored) {
            updateNotification("Offline - GPS fixes saved on phone");
        }
    }

    private void updateNotification(String text) {
        try {
            NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            nm.notify(NOTIFICATION_ID, buildNotification(text));
        } catch (Exception ignored) {
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        flushPendingAsync();
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        if (locationManager != null) {
            try {
                locationManager.removeUpdates(this);
            } catch (Exception ignored) {
            }
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
'''.replace("__PC_IP__", PC_TAILSCALE_IP).replace("__PC_PORT__", str(PC_PORT))

SETUP = r'''package com.androidbridge;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

public class OfflineLocationSetupActivity extends Activity {
    private static final int REQ_LOCATION = 8401;
    private TextView status;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);

        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(48, 64, 48, 48);
        layout.setGravity(Gravity.CENTER_HORIZONTAL);
        layout.setBackgroundColor(Color.rgb(16, 19, 24));

        TextView title = new TextView(this);
        title.setText("AndroidBridge Offline GPS");
        title.setTextColor(Color.WHITE);
        title.setTextSize(24);
        layout.addView(title, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        status = new TextView(this);
        status.setTextColor(Color.LTGRAY);
        status.setTextSize(15);
        status.setPadding(0, 30, 0, 30);
        layout.addView(status, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        Button start = new Button(this);
        start.setText("ENABLE OFFLINE GPS HISTORY");
        start.setOnClickListener(v -> ensurePermissionAndStart());
        layout.addView(start, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        Button settings = new Button(this);
        settings.setText("LOCATION PERMISSION SETTINGS");
        settings.setOnClickListener(v -> {
            Intent i = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
            i.setData(android.net.Uri.parse("package:" + getPackageName()));
            startActivity(i);
        });
        layout.addView(settings, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        setContentView(layout);
        refreshStatus();
    }

    private void refreshStatus() {
        boolean fine = checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)
                == PackageManager.PERMISSION_GRANTED;
        boolean background = Build.VERSION.SDK_INT < 29
                || checkSelfPermission(Manifest.permission.ACCESS_BACKGROUND_LOCATION)
                == PackageManager.PERMISSION_GRANTED;

        status.setText(
                "GPS works without Internet.\n\n"
                + "Precise location: " + (fine ? "GRANTED" : "NOT GRANTED") + "\n"
                + "Background restart permission: " + (background ? "GRANTED" : "OPTIONAL / NOT GRANTED") + "\n\n"
                + "Fixes are stored locally first. When Tailscale/network returns, "
                + "the queued history syncs to the AndroidBridge PC."
        );
    }

    private void ensurePermissionAndStart() {
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(
                    new String[] {
                            Manifest.permission.ACCESS_FINE_LOCATION,
                            Manifest.permission.ACCESS_COARSE_LOCATION
                    },
                    REQ_LOCATION
            );
            return;
        }
        startLogger();
    }

    private void startLogger() {
        Intent i = new Intent(this, OfflineLocationService.class);
        if (Build.VERSION.SDK_INT >= 26) {
            startForegroundService(i);
        } else {
            startService(i);
        }
        Toast.makeText(this, "Offline GPS history enabled", Toast.LENGTH_LONG).show();
        refreshStatus();
    }

    @Override
    public void onRequestPermissionsResult(
            int requestCode,
            String[] permissions,
            int[] grantResults
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQ_LOCATION
                && checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)
                == PackageManager.PERMISSION_GRANTED) {
            startLogger();
        } else {
            Toast.makeText(this, "Precise location permission is required", Toast.LENGTH_LONG).show();
        }
        refreshStatus();
    }

    @Override
    protected void onResume() {
        super.onResume();
        refreshStatus();
    }
}
'''

BOOT = r'''package com.androidbridge;

import android.Manifest;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;

public class OfflineLocationBootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (!Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())
                && !Intent.ACTION_MY_PACKAGE_REPLACED.equals(intent.getAction())) {
            return;
        }

        if (context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)
                != PackageManager.PERMISSION_GRANTED) {
            return;
        }

        if (Build.VERSION.SDK_INT >= 29
                && context.checkSelfPermission(Manifest.permission.ACCESS_BACKGROUND_LOCATION)
                != PackageManager.PERMISSION_GRANTED) {
            // Android 14+ may reject a location FGS launched from the background.
            // The logger will still work when started once from the visible setup Activity.
            return;
        }

        try {
            Intent service = new Intent(context, OfflineLocationService.class);
            if (Build.VERSION.SDK_INT >= 26) {
                context.startForegroundService(service);
            } else {
                context.startService(service);
            }
        } catch (Exception ignored) {
        }
    }
}
'''

def add_permission(root, name):
    full = "android.permission." + name
    for node in root.findall("uses-permission"):
        if node.get(A + "name") == full:
            return
    node = ET.Element("uses-permission")
    node.set(A + "name", full)
    # Keep permissions before <application>.
    app = root.find("application")
    idx = list(root).index(app) if app is not None else len(list(root))
    root.insert(idx, node)

def add_component(app, tag, name, attrs=None, actions=None, exported="false"):
    target = "." + name
    for node in app.findall(tag):
        if node.get(A + "name") in (target, PACKAGE + "." + name):
            node.set(A + "exported", exported)
            for k, v in (attrs or {}).items():
                node.set(A + k, v)
            return node
    node = ET.SubElement(app, tag)
    node.set(A + "name", target)
    node.set(A + "exported", exported)
    for k, v in (attrs or {}).items():
        node.set(A + k, v)
    if actions:
        flt = ET.SubElement(node, "intent-filter")
        for action in actions:
            a = ET.SubElement(flt, "action")
            a.set(A + "name", action)
    return node

def main():
    if not PROJECT.exists():
        raise SystemExit("Project not found: " + str(PROJECT))
    if not MANIFEST.exists():
        raise SystemExit("Manifest not found: " + str(MANIFEST))

    JAVA_DIR.mkdir(parents=True, exist_ok=True)
    (JAVA_DIR / "OfflineLocationService.java").write_text(SERVICE, encoding="utf-8")
    (JAVA_DIR / "OfflineLocationSetupActivity.java").write_text(SETUP, encoding="utf-8")
    (JAVA_DIR / "OfflineLocationBootReceiver.java").write_text(BOOT, encoding="utf-8")

    tree = ET.parse(MANIFEST)
    root = tree.getroot()
    for permission in [
        "ACCESS_FINE_LOCATION",
        "ACCESS_COARSE_LOCATION",
        "ACCESS_BACKGROUND_LOCATION",
        "FOREGROUND_SERVICE",
        "FOREGROUND_SERVICE_LOCATION",
        "INTERNET",
        "ACCESS_NETWORK_STATE",
        "RECEIVE_BOOT_COMPLETED",
    ]:
        add_permission(root, permission)

    app = root.find("application")
    if app is None:
        raise SystemExit("No <application> element in manifest.")

    add_component(
        app,
        "service",
        "OfflineLocationService",
        attrs={"foregroundServiceType": "location"}
    )
    # Export only the setup Activity so ADB can open it once on the user's
    # already-authorized remote phone. The service and boot receiver stay private.
    add_component(
        app,
        "activity",
        "OfflineLocationSetupActivity",
        exported="true"
    )
    add_component(
        app,
        "receiver",
        "OfflineLocationBootReceiver",
        actions=[
            "android.intent.action.BOOT_COMPLETED",
            "android.intent.action.MY_PACKAGE_REPLACED",
        ]
    )

    tree.write(MANIFEST, encoding="utf-8", xml_declaration=True)

    gradlew = PROJECT / "gradlew.bat"
    if not gradlew.exists():
        raise SystemExit("gradlew.bat not found in " + str(PROJECT))

    print("Offline GPS source installed.")
    print("Building with the PC's existing Android debug signing key...")
    result = subprocess.run(
        [str(gradlew), "assembleDebug"],
        cwd=str(PROJECT),
        shell=False
    )
    if result.returncode != 0:
        raise SystemExit(result.returncode)

    apks = sorted(
        (PROJECT / "app" / "build" / "outputs" / "apk").rglob("*.apk"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    if not apks:
        raise SystemExit("Build succeeded but no APK was found.")

    print("")
    print("READY APK:")
    print(apks[0])
    print("")
    print("Do NOT uninstall the existing Companion.")
    print("Install this APK in-place with adb install -r so existing app data is preserved.")
    print("Then open OfflineLocationSetupActivity once to grant/confirm location access.")

if __name__ == "__main__":
    main()
