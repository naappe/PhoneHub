package com.phonehub.notifier;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.app.admin.DevicePolicyManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.IBinder;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class LocalControlService extends Service {
    public static final int PORT = 8766;
    private static final String CHANNEL_ID = "phonehub_lan";
    private volatile boolean running = false;
    private ServerSocket serverSocket;
    private ExecutorService pool;
    private DevicePolicyManager dpm;
    private ComponentName admin;

    @Override
    public void onCreate() {
        super.onCreate();
        dpm = (DevicePolicyManager) getSystemService(Context.DEVICE_POLICY_SERVICE);
        admin = new ComponentName(this, PhoneHubDeviceAdminReceiver.class);
        createChannel();
        startForeground(44, new android.app.Notification.Builder(this, CHANNEL_ID)
                .setContentTitle("PhoneHub LAN Control")
                .setContentText("Local control service is running on port " + PORT)
                .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
                .build());
        startServer();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        running = false;
        try { if (serverSocket != null) serverSocket.close(); } catch (Exception ignored) {}
        if (pool != null) pool.shutdownNow();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }

    private void createChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID, "PhoneHub LAN Control", NotificationManager.IMPORTANCE_LOW);
            NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            nm.createNotificationChannel(channel);
        }
    }

    private void startServer() {
        if (running) return;
        running = true;
        pool = Executors.newCachedThreadPool();
        new Thread(() -> {
            try {
                serverSocket = new ServerSocket(PORT);
                while (running) {
                    Socket socket = serverSocket.accept();
                    pool.submit(() -> handle(socket));
                }
            } catch (Exception ignored) {
            }
        }, "PhoneHub-LAN").start();
    }

    private void handle(Socket socket) {
        try (Socket s = socket) {
            s.setSoTimeout(5000);
            BufferedReader reader = new BufferedReader(
                    new InputStreamReader(s.getInputStream(), StandardCharsets.UTF_8));
            String request = reader.readLine();
            if (request == null || request.isEmpty()) return;

            String[] parts = request.split(" ");
            String method = parts.length > 0 ? parts[0] : "";
            String path = parts.length > 1 ? parts[1] : "/";

            String auth = "";
            int contentLength = 0;
            String line;
            while ((line = reader.readLine()) != null && !line.isEmpty()) {
                String lower = line.toLowerCase(Locale.ROOT);
                if (lower.startsWith("x-phonehub-token:")) {
                    auth = line.substring(line.indexOf(':') + 1).trim();
                } else if (lower.startsWith("content-length:")) {
                    try { contentLength = Integer.parseInt(line.substring(line.indexOf(':') + 1).trim()); }
                    catch (Exception ignored) {}
                }
            }

            SharedPreferences prefs = getSharedPreferences("phonehub", MODE_PRIVATE);
            String expected = prefs.getString("lan_token", "");
            if (expected.isEmpty()) {
                expected = java.util.UUID.randomUUID().toString().replace("-", "");
                prefs.edit().putString("lan_token", expected).apply();
            }

            if (!expected.equals(auth)) {
                respond(s, 401, jsonError("Unauthorized"));
                return;
            }

            char[] bodyChars = new char[Math.max(contentLength, 0)];
            int read = 0;
            while (read < bodyChars.length) {
                int n = reader.read(bodyChars, read, bodyChars.length - read);
                if (n < 0) break;
                read += n;
            }
            String body = new String(bodyChars, 0, read);

            if ("GET".equals(method) && "/status".equals(path)) {
                respond(s, 200, buildStatus().toString());
            } else if ("GET".equals(method) && "/apps".equals(path)) {
                respond(s, 200, buildApps().toString());
            } else if ("POST".equals(method) && "/policy".equals(path)) {
                respond(s, 200, applyPolicy(body).toString());
            } else if ("POST".equals(method) && "/lock".equals(path)) {
                JSONObject out = new JSONObject();
                if (isOwner()) {
                    dpm.lockNow();
                    out.put("ok", true);
                } else {
                    out.put("ok", false).put("error", "Device Owner required");
                }
                respond(s, 200, out.toString());
            } else {
                respond(s, 404, jsonError("Not found"));
            }
        } catch (Exception ignored) {
        }
    }

    private boolean isOwner() {
        return dpm != null && dpm.isDeviceOwnerApp(getPackageName());
    }

    private JSONObject buildStatus() throws Exception {
        JSONObject out = new JSONObject();
        out.put("ok", true);
        out.put("package", getPackageName());
        out.put("deviceOwner", isOwner());
        out.put("port", PORT);
        out.put("lanIp", getLanIp());
        out.put("sdk", Build.VERSION.SDK_INT);
        out.put("model", Build.MANUFACTURER + " " + Build.MODEL);
        return out;
    }

    private JSONArray buildApps() throws Exception {
        JSONArray arr = new JSONArray();
        PackageManager pm = getPackageManager();
        List<PackageInfo> packages = pm.getInstalledPackages(0);
        for (PackageInfo info : packages) {
            JSONObject row = new JSONObject();
            row.put("package", info.packageName);
            row.put("name", String.valueOf(info.applicationInfo.loadLabel(pm)));
            arr.put(row);
        }
        return arr;
    }

    private JSONObject applyPolicy(String body) throws Exception {
        JSONObject input = new JSONObject(body == null || body.isEmpty() ? "{}" : body);
        JSONObject out = new JSONObject();
        if (!isOwner()) {
            return out.put("ok", false).put("error", "Device Owner required");
        }

        String action = input.optString("action", "");
        String pkg = input.optString("package", "");

        if ("suspend".equals(action) || "unsuspend".equals(action)) {
            if (pkg.isEmpty()) return out.put("ok", false).put("error", "Package required");
            boolean suspend = "suspend".equals(action);
            String[] failures = dpm.setPackagesSuspended(admin, new String[]{pkg}, suspend);
            out.put("ok", failures == null || failures.length == 0);
            out.put("action", action);
            out.put("package", pkg);
            if (failures != null && failures.length > 0) out.put("refused", failures[0]);
            return out;
        }

        if ("block_uninstall".equals(action) || "allow_uninstall".equals(action)) {
            if (pkg.isEmpty()) return out.put("ok", false).put("error", "Package required");
            dpm.setUninstallBlocked(admin, pkg, "block_uninstall".equals(action));
            return out.put("ok", true).put("action", action).put("package", pkg);
        }

        return out.put("ok", false).put("error", "Unsupported action");
    }

    private void respond(Socket socket, int code, String body) throws Exception {
        byte[] data = body.getBytes(StandardCharsets.UTF_8);
        String status = code == 200 ? "OK" : code == 401 ? "Unauthorized" : "Not Found";
        String headers = "HTTP/1.1 " + code + " " + status + "\r\n" +
                "Content-Type: application/json; charset=utf-8\r\n" +
                "Content-Length: " + data.length + "\r\n" +
                "Connection: close\r\n\r\n";
        OutputStream out = socket.getOutputStream();
        out.write(headers.getBytes(StandardCharsets.UTF_8));
        out.write(data);
        out.flush();
    }

    private String jsonError(String message) {
        try { return new JSONObject().put("ok", false).put("error", message).toString(); }
        catch (Exception e) { return "{\"ok\":false}"; }
    }

    public static String getLanIp() {
        try {
            for (NetworkInterface ni : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                for (InetAddress addr : Collections.list(ni.getInetAddresses())) {
                    if (!addr.isLoopbackAddress() && addr.getAddress().length == 4) {
                        String host = addr.getHostAddress();
                        if (host.startsWith("10.") || host.startsWith("192.168.") ||
                                host.matches("^172\\.(1[6-9]|2[0-9]|3[01])\\..*")) {
                            return host;
                        }
                    }
                }
            }
        } catch (Exception ignored) {}
        return "";
    }
}
