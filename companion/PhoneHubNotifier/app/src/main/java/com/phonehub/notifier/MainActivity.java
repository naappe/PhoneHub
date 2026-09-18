package com.phonehub.notifier;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.os.Bundle;
import android.provider.Settings;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

public class MainActivity extends Activity {
    private EditText endpoint;
    private EditText token;
    private TextView status;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        SharedPreferences prefs = getSharedPreferences("phonehub", MODE_PRIVATE);

        String intentEndpoint = getIntent().getStringExtra("endpoint");
        String intentToken = getIntent().getStringExtra("token");
        if (intentEndpoint != null && !intentEndpoint.isEmpty() && intentToken != null && !intentToken.isEmpty()) {
            prefs.edit().putString("endpoint", intentEndpoint).putString("token", intentToken).apply();
        }

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(40, 48, 40, 40);
        root.setBackgroundColor(Color.rgb(7, 17, 31));

        TextView title = new TextView(this);
        title.setText("PhoneHub Notifier");
        title.setTextColor(Color.WHITE);
        title.setTextSize(26);
        root.addView(title);

        TextView info = new TextView(this);
        info.setText("\nFor your own phone. Forwards notification title/text directly to your PhoneHub PC over Tailscale. No cloud service is used.\n");
        info.setTextColor(Color.LTGRAY);
        info.setTextSize(16);
        root.addView(info);

        endpoint = new EditText(this);
        endpoint.setHint("Receiver URL");
        endpoint.setText(prefs.getString("endpoint", ""));
        endpoint.setTextColor(Color.WHITE);
        endpoint.setHintTextColor(Color.GRAY);
        root.addView(endpoint);

        token = new EditText(this);
        token.setHint("Pairing token");
        token.setText(prefs.getString("token", ""));
        token.setTextColor(Color.WHITE);
        token.setHintTextColor(Color.GRAY);
        root.addView(token);

        Button save = new Button(this);
        save.setText("Save Connection");
        save.setOnClickListener(v -> {
            prefs.edit()
                    .putString("endpoint", endpoint.getText().toString().trim())
                    .putString("token", token.getText().toString().trim())
                    .apply();
            status.setText("Connection saved.");
        });
        root.addView(save);

        Button access = new Button(this);
        access.setText("Enable Notification Access");
        access.setOnClickListener(v -> startActivity(new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)));
        root.addView(access);

        Button test = new Button(this);
        test.setText("Send Test to PhoneHub");
        test.setOnClickListener(v -> NotificationForwarderService.sendTest(this));
        root.addView(test);

        status = new TextView(this);
        status.setText("\n1. Save connection\n2. Enable Notification Access\n3. Send Test\n\nAfter this, SMS/WhatsApp notifications can be forwarded while the app UI is closed.");
        status.setTextColor(Color.rgb(134, 239, 172));
        status.setTextSize(15);
        root.addView(status);

        setContentView(root);
    }
}
