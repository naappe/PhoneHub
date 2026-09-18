package com.phonehub.notifier;

import android.app.Activity;
import android.app.admin.DevicePolicyManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.os.Bundle;
import android.os.UserManager;
import android.provider.Settings;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

public class MainActivity extends Activity {
    private EditText endpoint;
    private EditText token;
    private EditText packageName;
    private TextView status;
    private DevicePolicyManager dpm;
    private ComponentName admin;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        dpm = (DevicePolicyManager) getSystemService(Context.DEVICE_POLICY_SERVICE);
        admin = new ComponentName(this, PhoneHubDeviceAdminReceiver.class);

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
        info.setText("\nNotification forwarding + optional Device Owner app controls for your own managed phone. No cloud service is used.\n");
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

        TextView policyTitle = new TextView(this);
        policyTitle.setText("\nApp Control");
        policyTitle.setTextColor(Color.WHITE);
        policyTitle.setTextSize(20);
        root.addView(policyTitle);

        packageName = new EditText(this);
        packageName.setHint("Package name, e.g. com.example.app");
        packageName.setTextColor(Color.WHITE);
        packageName.setHintTextColor(Color.GRAY);
        root.addView(packageName);

        Button suspend = new Button(this);
        suspend.setText("Suspend App");
        suspend.setOnClickListener(v -> runPackagePolicy(true));
        root.addView(suspend);

        Button unsuspend = new Button(this);
        unsuspend.setText("Unsuspend App");
        unsuspend.setOnClickListener(v -> runPackagePolicy(false));
        root.addView(unsuspend);

        Button blockUninstall = new Button(this);
        blockUninstall.setText("Block Uninstall");
        blockUninstall.setOnClickListener(v -> setUninstallBlocked(true));
        root.addView(blockUninstall);

        Button allowUninstall = new Button(this);
        allowUninstall.setText("Allow Uninstall");
        allowUninstall.setOnClickListener(v -> setUninstallBlocked(false));
        root.addView(allowUninstall);

        Button blockInstalls = new Button(this);
        blockInstalls.setText("Block App Installs");
        blockInstalls.setOnClickListener(v -> setInstallRestrictions(true));
        root.addView(blockInstalls);

        Button allowInstalls = new Button(this);
        allowInstalls.setText("Allow App Installs");
        allowInstalls.setOnClickListener(v -> setInstallRestrictions(false));
        root.addView(allowInstalls);

        status = new TextView(this);
        status.setTextColor(Color.rgb(134, 239, 172));
        status.setTextSize(15);
        root.addView(status);

        setContentView(root);

        handlePolicyIntent(getIntent());
        refreshStatus();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handlePolicyIntent(intent);
        refreshStatus();
    }

    private boolean isDeviceOwner() {
        return dpm != null && dpm.isDeviceOwnerApp(getPackageName());
    }

    private void refreshStatus() {
        status.setText(
                "\nNotification forwarding ready.\n" +
                "Device Owner: " + (isDeviceOwner() ? "YES" : "NO") + "\n" +
                (isDeviceOwner()
                        ? "App Control is available."
                        : "App Control requires Device Owner provisioning. PhoneHub will not enable this automatically.")
        );
    }

    private void handlePolicyIntent(Intent intent) {
        if (intent == null) return;
        String action = intent.getStringExtra("policy_action");
        String pkg = intent.getStringExtra("package");
        if (pkg != null && packageName != null) packageName.setText(pkg);
        if (action == null || action.isEmpty()) return;

        switch (action) {
            case "suspend":
                runPackagePolicy(true);
                break;
            case "unsuspend":
                runPackagePolicy(false);
                break;
            case "block_uninstall":
                setUninstallBlocked(true);
                break;
            case "allow_uninstall":
                setUninstallBlocked(false);
                break;
            case "block_installs":
                setInstallRestrictions(true);
                break;
            case "allow_installs":
                setInstallRestrictions(false);
                break;
            default:
                break;
        }
    }

    private String selectedPackage() {
        return packageName == null ? "" : packageName.getText().toString().trim();
    }

    private void runPackagePolicy(boolean suspend) {
        if (!isDeviceOwner()) {
            status.setText("Device Owner is required for app suspension.");
            return;
        }

        String pkg = selectedPackage();
        if (pkg.isEmpty()) {
            status.setText("Enter a package name first.");
            return;
        }

        try {
            String[] failures = dpm.setPackagesSuspended(admin, new String[]{pkg}, suspend);
            if (failures != null && failures.length > 0) {
                status.setText("Android refused to change this package: " + failures[0]);
            } else {
                status.setText(pkg + (suspend ? " suspended." : " unsuspended."));
            }
        } catch (Exception e) {
            status.setText("Policy failed: " + e.getMessage());
        }
    }

    private void setUninstallBlocked(boolean blocked) {
        if (!isDeviceOwner()) {
            status.setText("Device Owner is required for uninstall protection.");
            return;
        }

        String pkg = selectedPackage();
        if (pkg.isEmpty()) {
            status.setText("Enter a package name first.");
            return;
        }

        try {
            dpm.setUninstallBlocked(admin, pkg, blocked);
            status.setText((blocked ? "Uninstall blocked for " : "Uninstall allowed for ") + pkg);
        } catch (Exception e) {
            status.setText("Policy failed: " + e.getMessage());
        }
    }

    private void setInstallRestrictions(boolean blocked) {
        if (!isDeviceOwner()) {
            status.setText("Device Owner is required for install restrictions.");
            return;
        }

        try {
            if (blocked) {
                dpm.addUserRestriction(admin, UserManager.DISALLOW_INSTALL_APPS);
                dpm.addUserRestriction(admin, UserManager.DISALLOW_INSTALL_UNKNOWN_SOURCES);
                status.setText("App installation restrictions enabled.");
            } else {
                dpm.clearUserRestriction(admin, UserManager.DISALLOW_INSTALL_APPS);
                dpm.clearUserRestriction(admin, UserManager.DISALLOW_INSTALL_UNKNOWN_SOURCES);
                status.setText("App installation restrictions cleared.");
            }
        } catch (Exception e) {
            status.setText("Policy failed: " + e.getMessage());
        }
    }
}
