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

    private TextView stateText;
    private TextView helpText;
    private Button connectButton;
    private Button advancedButton;
    private LinearLayout advancedPanel;

    private EditText phoneAddress;
    private EditText privateKey;
    private EditText publicKey;
    private EditText pcPublicKey;
    private EditText endpoint;
    private EditText allowedIps;
    private EditText keepalive;

    private volatile boolean pendingConnect = false;
    private volatile Tunnel.State currentState = Tunnel.State.DOWN;

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
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        applyIncomingConfig(intent);
        refreshState();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (backend != null) refreshState();
    }

    @Override
    protected void onDestroy() {
        worker.shutdown();
        super.onDestroy();
    }

    private void buildUi() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(Color.rgb(7, 17, 31));

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(42, 56, 42, 56);
        root.setBackgroundColor(Color.rgb(7, 17, 31));
        scroll.addView(root);

        TextView title = label("PhoneHub One", 30, Color.WHITE);
        root.addView(title);

        TextView subtitle = label("Private connection to your PC", 16, Color.rgb(160, 174, 192));
        subtitle.setPadding(0, 4, 0, 36);
        root.addView(subtitle);

        TextView caption = label("PRIVATE LINK", 13, Color.rgb(120, 145, 170));
        root.addView(caption);

        stateText = label("CHECKING", 34, Color.WHITE);
        stateText.setPadding(0, 8, 0, 10);
        root.addView(stateText);

        helpText = label("Checking connection…", 15, Color.rgb(180, 190, 205));
        helpText.setPadding(0, 0, 0, 30);
        root.addView(helpText);

        connectButton = button("CONNECT TO PC");
        connectButton.setTextSize(18);
        connectButton.setMinHeight(150);
        connectButton.setOnClickListener(v -> {
            if (currentState == Tunnel.State.UP) disconnectTunnel();
            else requestConnect();
        });
        root.addView(connectButton);

        TextView automatic = label(
                "PhoneHub on the PC sends the connection settings automatically. " +
                "You only need to approve Android's VPN permission when asked.",
                14, Color.rgb(145, 160, 180));
        automatic.setPadding(0, 24, 0, 24);
        root.addView(automatic);

        advancedButton = button("Advanced");
        advancedButton.setOnClickListener(v -> toggleAdvanced());
        root.addView(advancedButton);

        advancedPanel = new LinearLayout(this);
        advancedPanel.setOrientation(LinearLayout.VERTICAL);
        advancedPanel.setVisibility(View.GONE);
        advancedPanel.setPadding(0, 18, 0, 0);
        root.addView(advancedPanel);

        phoneAddress = input("Phone tunnel address", false);
        privateKey = input("Phone private key", true);
        publicKey = input("Phone public key", false);
        publicKey.setEnabled(false);
        pcPublicKey = input("PC public key", false);
        endpoint = input("PC endpoint", false);
        allowedIps = input("Allowed IPs", false);
        keepalive = input("Keepalive seconds", false);
        keepalive.setInputType(InputType.TYPE_CLASS_NUMBER);

        advancedPanel.addView(phoneAddress);
        advancedPanel.addView(privateKey);
        advancedPanel.addView(publicKey);
        advancedPanel.addView(pcPublicKey);
        advancedPanel.addView(endpoint);
        advancedPanel.addView(allowedIps);
        advancedPanel.addView(keepalive);

        Button save = button("Save advanced settings");
        save.setOnClickListener(v -> {
            saveValues();
            showMessage("Settings saved.");
        });
        advancedPanel.addView(save);

        Button newKeys = button("Generate new phone keys");
        newKeys.setOnClickListener(v -> generateKeys());
        advancedPanel.addView(newKeys);

        Button refresh = button("Refresh status");
        refresh.setOnClickListener(v -> refreshState());
        advancedPanel.addView(refresh);

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
        e.setHintTextColor(Color.rgb(110, 125, 145));
        e.setTextColor(Color.WHITE);
        e.setSingleLine(true);
        e.setPadding(14, 14, 14, 14);
        if (secret) {
            e.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        }
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

    private void toggleAdvanced() {
        boolean open = advancedPanel.getVisibility() == View.VISIBLE;
        advancedPanel.setVisibility(open ? View.GONE : View.VISIBLE);
        advancedButton.setText(open ? "Advanced" : "Hide advanced");
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

        boolean autoSave = intent.getBooleanExtra("auto_save", false)
                || intent.getBooleanExtra("auto_pair", false);
        if (autoSave) saveValues();

        boolean autoConnect = intent.getBooleanExtra("auto_connect", false);
        if (autoConnect) {
            connectButton.postDelayed(this::requestConnect, 500);
        } else if (autoSave) {
            showMessage("PC configuration received. Tap Connect to finish.");
        }
    }

    private void setIfPresent(EditText field, Intent intent, String key) {
        String value = intent.getStringExtra(key);
        if (value != null && !value.trim().isEmpty()) field.setText(value.trim());
    }

    private void loadSaved() {
        phoneAddress.setText(prefs.getString("phone_address", "10.77.0.2/32"));
        privateKey.setText(prefs.getString("private_key", ""));
        publicKey.setText(prefs.getString("public_key", ""));
        pcPublicKey.setText(prefs.getString("pc_public_key", ""));
        endpoint.setText(prefs.getString("endpoint", ""));
        allowedIps.setText(prefs.getString("allowed_ips", "10.77.0.1/32"));
        keepalive.setText(prefs.getString("keepalive", "25"));
        if (privateKey.getText().toString().trim().isEmpty()) generateKeys();
    }

    private void generateKeys() {
        try {
            KeyPair keys = new KeyPair();
            privateKey.setText(keys.getPrivateKey().toBase64());
            publicKey.setText(keys.getPublicKey().toBase64());
            saveValues();
            showMessage("New phone keys generated.");
        } catch (Exception e) {
            showError("Key generation failed", e);
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
            throw new IllegalArgumentException("Connect from PhoneHub on the PC first so the app can receive its setup.");
        }

        StringBuilder cfg = new StringBuilder();
        cfg.append("[Interface]\n");
        cfg.append("PrivateKey = ").append(priv).append("\n");
        cfg.append("Address = ").append(phoneAddr).append("\n\n");
        cfg.append("[Peer]\n");
        cfg.append("PublicKey = ").append(peerKey).append("\n");
        cfg.append("Endpoint = ").append(peerEndpoint).append("\n");
        cfg.append("AllowedIPs = ").append(ips).append("\n");
        if (!ka.isEmpty()) cfg.append("PersistentKeepalive = ").append(ka).append("\n");
        return cfg.toString();
    }

    private void requestConnect() {
        saveValues();
        try {
            buildConfigText();
        } catch (Exception e) {
            stateText.setText("SETUP NEEDED");
            stateText.setTextColor(Color.rgb(251, 191, 36));
            helpText.setText(e.getMessage());
            connectButton.setText("CONNECT TO PC");
            return;
        }

        Intent permission = VpnService.prepare(this);
        if (permission != null) {
            pendingConnect = true;
            helpText.setText("Approve the Android VPN connection request.");
            startActivityForResult(permission, VPN_REQUEST);
        } else {
            connectTunnel();
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != VPN_REQUEST) return;

        if (resultCode == RESULT_OK && pendingConnect) {
            pendingConnect = false;
            connectTunnel();
        } else {
            pendingConnect = false;
            stateText.setText("PERMISSION NEEDED");
            stateText.setTextColor(Color.rgb(251, 191, 36));
            helpText.setText("Tap Connect and allow Android to create the VPN connection.");
        }
    }

    private void connectTunnel() {
        stateText.setText("CONNECTING");
        stateText.setTextColor(Color.WHITE);
        helpText.setText("Starting the encrypted private link…");
        connectButton.setEnabled(false);

        final String text;
        try {
            text = buildConfigText();
        } catch (Exception e) {
            connectButton.setEnabled(true);
            showError("Setup needed", e);
            return;
        }

        worker.submit(() -> {
            try {
                Config config = Config.parse(new BufferedReader(new StringReader(text)));
                Tunnel.State result = backend.setState(tunnel, Tunnel.State.UP, config);
                runOnUiThread(() -> renderState(result));
            } catch (Exception e) {
                runOnUiThread(() -> {
                    connectButton.setEnabled(true);
                    stateText.setText("NOT CONNECTED");
                    stateText.setTextColor(Color.rgb(248, 113, 113));
                    helpText.setText("Connection failed: " + readable(e));
                    connectButton.setText("TRY AGAIN");
                });
            }
        });
    }

    private void disconnectTunnel() {
        stateText.setText("DISCONNECTING");
        connectButton.setEnabled(false);
        worker.submit(() -> {
            try {
                Tunnel.State result = backend.setState(tunnel, Tunnel.State.DOWN, null);
                runOnUiThread(() -> renderState(result));
            } catch (Exception e) {
                runOnUiThread(() -> {
                    connectButton.setEnabled(true);
                    showError("Disconnect failed", e);
                });
            }
        });
    }

    private void refreshState() {
        worker.submit(() -> {
            try {
                Tunnel.State state = backend.getState(tunnel);
                runOnUiThread(() -> renderState(state));
            } catch (Exception e) {
                runOnUiThread(() -> showError("Status check failed", e));
            }
        });
    }

    private void renderState(Tunnel.State state) {
        currentState = state;
        connectButton.setEnabled(true);
        if (state == Tunnel.State.UP) {
            stateText.setText("CONNECTED");
            stateText.setTextColor(Color.rgb(74, 222, 128));
            helpText.setText("Private Link is active.");
            connectButton.setText("DISCONNECT");
        } else {
            stateText.setText("NOT CONNECTED");
            stateText.setTextColor(Color.rgb(248, 113, 113));
            helpText.setText("Tap Connect to start the private link.");
            connectButton.setText("CONNECT TO PC");
        }
    }

    private void showMessage(String message) {
        helpText.setText(message);
    }

    private void showError(String prefix, Exception e) {
        stateText.setText("ACTION REQUIRED");
        stateText.setTextColor(Color.rgb(251, 191, 36));
        helpText.setText(prefix + ": " + readable(e));
        connectButton.setEnabled(true);
    }

    private String readable(Exception e) {
        String msg = e.getMessage();
        return (msg == null || msg.trim().isEmpty()) ? e.getClass().getSimpleName() : msg;
    }

    private final class LinkTunnel implements Tunnel {
        @Override
        public String getName() {
            return "phonehublink";
        }

        @Override
        public void onStateChange(State newState) {
            runOnUiThread(() -> renderState(newState));
        }
    }
}
