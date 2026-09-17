package mv.phonehub.test;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private EditText pcIp;
    private EditText message;
    private TextView status;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(32, 40, 32, 40);
        scroll.addView(root);

        TextView title = new TextView(this);
        title.setText("PhoneHub Transport Test");
        title.setTextSize(28);
        title.setTextColor(Color.BLACK);
        title.setGravity(Gravity.CENTER_HORIZONTAL);
        root.addView(title);

        TextView path = new TextView(this);
        path.setText("PHONE → Tailscale → PC");
        path.setTextSize(16);
        path.setGravity(Gravity.CENTER_HORIZONTAL);
        path.setPadding(0, 12, 0, 32);
        root.addView(path);

        TextView ipLabel = new TextView(this);
        ipLabel.setText("PC Tailscale IP");
        root.addView(ipLabel);

        pcIp = new EditText(this);
        pcIp.setSingleLine(true);
        pcIp.setHint("100.x.x.x");
        pcIp.setText("100.125.11.48");
        root.addView(pcIp);

        Button ping = new Button(this);
        ping.setText("CHECK PC CONNECTION");
        ping.setOnClickListener(v -> pingPc());
        root.addView(ping);

        TextView msgLabel = new TextView(this);
        msgLabel.setText("Small test message");
        msgLabel.setPadding(0, 28, 0, 0);
        root.addView(msgLabel);

        message = new EditText(this);
        message.setMinLines(4);
        message.setGravity(Gravity.TOP);
        message.setText("Hello from PhoneHub Android test");
        root.addView(message);

        Button send = new Button(this);
        send.setText("SEND SMALL FILE TO PC");
        send.setOnClickListener(v -> sendText());
        root.addView(send);

        status = new TextView(this);
        status.setText("Status: ready");
        status.setTextSize(17);
        status.setPadding(0, 30, 0, 0);
        root.addView(status);

        TextView note = new TextView(this);
        note.setText("This is a temporary transport test. It does not use ADB or scrcpy.");
        note.setPadding(0, 28, 0, 0);
        root.addView(note);

        setContentView(scroll);
    }

    private String baseUrl() {
        String ip = pcIp.getText().toString().trim();
        return "http://" + ip + ":8765";
    }

    private void pingPc() {
        setBusy("Checking PC through Tailscale...");
        executor.execute(() -> {
            try {
                HttpURLConnection c = (HttpURLConnection) new URL(baseUrl() + "/ping").openConnection();
                c.setConnectTimeout(5000);
                c.setReadTimeout(5000);
                c.setRequestMethod("GET");
                String body = read(c);
                int code = c.getResponseCode();
                if (code == 200 && body.contains("PHONEHUB-PC-ONLINE")) {
                    showStatus("PC ONLINE — Tailscale path works");
                } else {
                    showStatus("PC replied, but test response was unexpected: " + code + " " + body);
                }
            } catch (Exception e) {
                showStatus("OFFLINE / NOT REACHABLE: " + e.getMessage());
            }
        });
    }

    private void sendText() {
        final String text = message.getText().toString();
        setBusy("Sending phone-test.txt...");
        executor.execute(() -> {
            try {
                HttpURLConnection c = (HttpURLConnection) new URL(baseUrl() + "/upload?name=phone-test.txt").openConnection();
                c.setConnectTimeout(5000);
                c.setReadTimeout(5000);
                c.setDoOutput(true);
                c.setRequestMethod("POST");
                c.setRequestProperty("Content-Type", "text/plain; charset=utf-8");
                byte[] data = text.getBytes(StandardCharsets.UTF_8);
                c.setFixedLengthStreamingMode(data.length);
                try (OutputStream out = c.getOutputStream()) {
                    out.write(data);
                }
                String body = read(c);
                if (c.getResponseCode() == 200) {
                    showStatus("SENT — PC saved phone-test.txt\n" + body);
                } else {
                    showStatus("Send failed: HTTP " + c.getResponseCode() + " " + body);
                }
            } catch (Exception e) {
                showStatus("SEND FAILED: " + e.getMessage());
            }
        });
    }

    private String read(HttpURLConnection c) throws Exception {
        InputStream in = c.getResponseCode() >= 400 ? c.getErrorStream() : c.getInputStream();
        if (in == null) return "";
        BufferedReader r = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8));
        StringBuilder b = new StringBuilder();
        String line;
        while ((line = r.readLine()) != null) b.append(line).append('\n');
        return b.toString().trim();
    }

    private void setBusy(String text) {
        status.setText("Status: " + text);
    }

    private void showStatus(String text) {
        runOnUiThread(() -> status.setText("Status: " + text));
    }

    @Override
    protected void onDestroy() {
        executor.shutdownNow();
        super.onDestroy();
    }
}
