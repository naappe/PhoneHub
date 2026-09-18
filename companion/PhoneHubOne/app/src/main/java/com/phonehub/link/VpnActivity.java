package com.phonehub.link;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.VpnService;
import android.os.Bundle;
import android.text.InputType;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import com.wireguard.android.backend.GoBackend;
import com.wireguard.android.backend.Tunnel;
import com.wireguard.config.Config;
import com.wireguard.crypto.KeyPair;

import java.io.BufferedReader;
import java.io.StringReader;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class VpnActivity extends Activity {
    private static final int VPN_REQUEST = 7001;
    private static final String PREFS = "phonehub_link";

    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final LinkTunnel tunnel = new LinkTunnel();

    private GoBackend backend;
    private SharedPreferences prefs;

    private EditText phoneAddress;
    private EditText privateKey;
    private EditText publicKey;
    private EditText pcPublicKey;
    private EditText endpoint;
    private EditText allowedIps;
    private EditText keepalive;
    private TextView status;

    private volatile boolean pendingConnect = false;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        backend = new GoBackend(getApplicationContext());
        buildUi();
        loadSaved();
        applyIncomingConfig(getIntent());
        refreshState();
    }

    @Override
    protected void onDestroy() {
        worker.shutdown();
        super.onDestroy();
    }

    private void buildUi() {
        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(36, 42, 36, 48);
        root.setBackgroundColor(Color.rgb(7, 17, 31));
        scroll.addView(root);

        TextView title = label("PhoneHub One · Private Link", 28, Color.WHITE);
        root.addView(title);

        TextView subtitle = label(
                "Private WireGuard link for PhoneHub. Installs beside PhoneHub Notifier and does not replace Device Owner.",
                15, Color.LTGRAY);
        subtitle.setPadding(0, 8, 0, 22);
        root.addView(subtitle);

        status = label("Status: checking...", 16, Color.rgb(130, 220, 170));
        status.setTextIsSelectable(true);
        status.setPadding(0, 0, 0, 18);
        root.addView(status);

        phoneAddress = input("Phone tunnel address, e.g. 10.77.0.2/32", false);
        privateKey = input("Phone private key", true);
        publicKey = input("Phone public key", false);
        publicKey.setEnabled(false);
        pcPublicKey = input("PC public key", false);
        endpoint = input("PC endpoint, e.g. 192.168.1.20:51820", false);
        allowedIps = input("Allowed IPs, e.g. 10.77.0.1/32", false);
        keepalive = input("Persistent keepalive seconds", false);
        keepalive.setInputType(InputType.TYPE_CLASS_NUMBER);

        root.addView(phoneAddress);
        root.addView(privateKey);
        root.addView(publicKey);
        root.addView(pcPublicKey);
        root.addView(endpoint);
        root.addView(allowedIps);
        root.addView(keepalive);

        Button generate = button("Generate Phone Keys");
        generate.setOnClickListener(v -> generateKeys());
        root.addView(generate);

        Button save = button("Save Configuration");
        save.setOnClickListener(v -> {
            saveValues();
            setStatus("Configuration saved.");
        });
        root.addView(save);

        Button connect = button("Connect Private Link");
        connect.setOnClickListener(v -> requestConnect());
        root.addView(connect);

        Button disconnect = button("Disconnect");
        disconnect.setOnClickListener(v -> disconnectTunnel());
        root.addView(disconnect);

        Button refresh = button("Refresh Status");
        refresh.setOnClickListener(v -> refreshState());
        root.addView(refresh);

        TextView note = label(
                "This app creates the encrypted phone side of the link. The PC must have a matching WireGuard peer. " +
                "On the same Wi-Fi, use the PC's LAN IP as Endpoint. For access across the internet, the PC endpoint must be reachable " +
                "or a relay/server is required.",
                14, Color.LTGRAY);
        note.setPadding(0, 22, 0, 0);
        root.addView(note);

        setContentView(scroll);
    }

    private TextView label(String text, int size, int color) {
        TextView v = new TextView(this);
        v.setText(text);
        v.setTextSize(size);
        v.setTextColor(color);
        return v;
    }

    private EditText input(String hint, boolean secret) {
        EditText e = new EditText(this);
        e.setHint(hint);
        e.setHintTextColor(Color.GRAY);
        e.setTextColor(Color.WHITE);
        e.setSingleLine(true);
        if (secret) {
            e.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        }
        e.setPadding(12, 12, 12, 12);
        return e;
    }

    private Button button(String text) {
        Button b = new Button(this);
        b.setText(text);
        b.setAllCaps(false);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.setMargins(0, 8, 0, 0);
        b.setLayoutParams(lp);
        return b;
    }

    private void applyIncomingConfig(Intent intent) {
        if (intent == null) return;

        setIfPresent(phoneAddress, intent, "phone_address");
        setIfPresent(privateKey, intent, "private_key");
        setIfPresent(publicKey, intent, "public_key");
        setIfPresent(pcPublicKey, intent, "pc_public_key");
        setIfPresent(endpoint, intent, "endpoint");
        setIfPresent(allowedIps, intent, "allowed_ips");
        setIfPresent(keepalive, intent, "keepalive");

        if (intent.getBooleanExtra("auto_save", false)) {
            saveValues();
            setStatus("PhoneHub PC paired this private link automatically.");
        }

        if (intent.getBooleanExtra("auto_connect", false)) {
            phoneAddress.postDelayed(this::requestConnect, 450);
        }
    }

    private void setIfPresent(EditText field, Intent intent, String key) {
        String value = intent.getStringExtra(key);
        if (value != null && !value.trim().isEmpty()) {
            field.setText(value.trim());
        }
    }

    private void loadSaved() {
        phoneAddress.setText(prefs.getString("phone_address", "10.77.0.2/32"));
        privateKey.setText(prefs.getString("private_key", ""));
        publicKey.setText(prefs.getString("public_key", ""));
        pcPublicKey.setText(prefs.getString("pc_public_key", ""));
        endpoint.setText(prefs.getString("endpoint", ""));
        allowedIps.setText(prefs.getString("allowed_ips", "10.77.0.1/32"));
        keepalive.setText(prefs.getString("keepalive", "25"));

        if (privateKey.getText().toString().trim().isEmpty()) {
            generateKeys();
        }
    }

    private void generateKeys() {
        try {
            KeyPair keys = new KeyPair();
            privateKey.setText(keys.getPrivateKey().toBase64());
            publicKey.setText(keys.getPublicKey().toBase64());
            saveValues();
            setStatus("New WireGuard key pair generated.");
        } catch (Exception e) {
            setStatus("Key generation failed: " + e.getMessage());
        }
    }

    private void saveValues() {
        prefs.edit()
                .putString("phone_address", phoneAddress.getText().toString().trim())
                .putString("private_key", privateKey.getText().toString().trim())
                .putString("public_key", publicKey.getText().toString().trim())
                .putString("pc_public_key", pcPublicKey.getText().toString().trim())
                .putString("endpoint", endpoint.getText().toString().trim())
                .putString("allowed_ips", allowedIps.getText().toString().trim())
                .putString("keepalive", keepalive.getText().toString().trim())
                .apply();
    }

    private String buildConfigText() {
        String phoneAddr = phoneAddress.getText().toString().trim();
        String priv = privateKey.getText().toString().trim();
        String peerKey = pcPublicKey.getText().toString().trim();
        String peerEndpoint = endpoint.getText().toString().trim();
        String ips = allowedIps.getText().toString().trim();
        String ka = keepalive.getText().toString().trim();

        if (phoneAddr.isEmpty() || priv.isEmpty() || peerKey.isEmpty() || peerEndpoint.isEmpty() || ips.isEmpty()) {
            throw new IllegalArgumentException("Phone address, keys, endpoint and allowed IPs are required.");
        }

        StringBuilder cfg = new StringBuilder();
        cfg.append("[Interface]\n");
        cfg.append("PrivateKey = ").append(priv).append("\n");
        cfg.append("Address = ").append(phoneAddr).append("\n\n");
        cfg.append("[Peer]\n");
        cfg.append("PublicKey = ").append(peerKey).append("\n");
        cfg.append("Endpoint = ").append(peerEndpoint).append("\n");
        cfg.append("AllowedIPs = ").append(ips).append("\n");
        if (!ka.isEmpty()) {
            cfg.append("PersistentKeepalive = ").append(ka).append("\n");
        }
        return cfg.toString();
    }

    private void requestConnect() {
        saveValues();

        try {
            buildConfigText();
        } catch (Exception e) {
            setStatus("Config error: " + e.getMessage());
            return;
        }

        Intent permission = VpnService.prepare(this);
        if (permission != null) {
            pendingConnect = true;
            startActivityForResult(permission, VPN_REQUEST);
        } else {
            connectTunnel();
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == VPN_REQUEST) {
            if (resultCode == RESULT_OK && pendingConnect) {
                pendingConnect = false;
                connectTunnel();
            } else {
                pendingConnect = false;
                setStatus("VPN permission was not granted.");
            }
        }
    }

    private void connectTunnel() {
        setStatus("Connecting...");
        final String text;
        try {
            text = buildConfigText();
        } catch (Exception e) {
            setStatus("Config error: " + e.getMessage());
            return;
        }

        worker.submit(() -> {
            try {
                Config config = Config.parse(new BufferedReader(new StringReader(text)));
                Tunnel.State result = backend.setState(tunnel, Tunnel.State.UP, config);
                runOnUiThread(() -> setStatus("Private link: " + result.name()));
            } catch (Exception e) {
                runOnUiThread(() -> setStatus("Connect failed: " + readable(e)));
            }
        });
    }

    private void disconnectTunnel() {
        setStatus("Disconnecting...");
        worker.submit(() -> {
            try {
                Tunnel.State result = backend.setState(tunnel, Tunnel.State.DOWN, null);
                runOnUiThread(() -> setStatus("Private link: " + result.name()));
            } catch (Exception e) {
                runOnUiThread(() -> setStatus("Disconnect failed: " + readable(e)));
            }
        });
    }

    private void refreshState() {
        worker.submit(() -> {
            try {
                Tunnel.State state = backend.getState(tunnel);
                runOnUiThread(() -> setStatus("Private link: " + state.name()));
            } catch (Exception e) {
                runOnUiThread(() -> setStatus("Status error: " + readable(e)));
            }
        });
    }

    private String readable(Exception e) {
        String msg = e.getMessage();
        return (msg == null || msg.trim().isEmpty()) ? e.getClass().getSimpleName() : msg;
    }

    private void setStatus(String text) {
        status.setText("Status: " + text);
    }

    private final class LinkTunnel implements Tunnel {
        @Override
        public String getName() {
            return "phonehublink";
        }

        @Override
        public void onStateChange(State newState) {
            runOnUiThread(() -> setStatus("Private link: " + newState.name()));
        }
    }
}
