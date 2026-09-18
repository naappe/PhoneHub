package com.phonehub.notifier;

import android.app.Notification;
import android.content.Context;
import android.content.SharedPreferences;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;
import android.text.TextUtils;

import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

public class NotificationForwarderService extends NotificationListenerService {

    @Override
    public void onNotificationPosted(StatusBarNotification sbn) {
        if (sbn == null || sbn.getNotification() == null) return;

        Notification n = sbn.getNotification();
        CharSequence titleCs = n.extras.getCharSequence(Notification.EXTRA_TITLE);
        CharSequence textCs = n.extras.getCharSequence(Notification.EXTRA_BIG_TEXT);
        if (TextUtils.isEmpty(textCs)) {
            textCs = n.extras.getCharSequence(Notification.EXTRA_TEXT);
        }

        String title = titleCs == null ? "" : titleCs.toString();
        String text = textCs == null ? "" : textCs.toString();
        if (title.isEmpty() && text.isEmpty()) return;

        forward(getApplicationContext(), sbn.getPackageName(), title, text, sbn.getPostTime());
    }

    public static void sendTest(Context context) {
        forward(context, "com.phonehub.notifier", "PhoneHub Test", "Notification Listener companion is connected.", System.currentTimeMillis());
    }

    private static void forward(Context context, String pkg, String title, String text, long postedAt) {
        SharedPreferences prefs = context.getSharedPreferences("phonehub", Context.MODE_PRIVATE);
        String endpoint = prefs.getString("endpoint", "").trim();
        String token = prefs.getString("token", "").trim();
        if (endpoint.isEmpty() || token.isEmpty()) return;

        new Thread(() -> {
            HttpURLConnection conn = null;
            try {
                JSONObject body = new JSONObject();
                body.put("package", pkg);
                body.put("title", title);
                body.put("text", text);
                body.put("posted_at", postedAt);

                byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
                conn = (HttpURLConnection) new URL(endpoint).openConnection();
                conn.setConnectTimeout(5000);
                conn.setReadTimeout(5000);
                conn.setRequestMethod("POST");
                conn.setDoOutput(true);
                conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                conn.setRequestProperty("X-PhoneHub-Token", token);
                conn.setFixedLengthStreamingMode(bytes.length);

                try (OutputStream out = conn.getOutputStream()) {
                    out.write(bytes);
                }
                conn.getResponseCode();
            } catch (Exception ignored) {
            } finally {
                if (conn != null) conn.disconnect();
            }
        }, "PhoneHubNotifyForward").start();
    }
}
