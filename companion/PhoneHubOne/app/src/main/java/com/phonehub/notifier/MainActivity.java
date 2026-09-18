package com.phonehub.notifier;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;

import com.phonehub.link.VpnActivity;

/**
 * Compatibility launcher for PhoneHub One.
 * Keeps the historical activity name used by the PC application, then forwards
 * every pairing extra to the simplified Private Link screen.
 */
public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        openPrivateLink(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        openPrivateLink(intent);
    }

    private void openPrivateLink(Intent source) {
        Intent vpn = new Intent(this, VpnActivity.class);
        if (source != null && source.getExtras() != null) {
            vpn.putExtras(source.getExtras());
        }
        if (source != null && source.getBooleanExtra("auto_pair", false)) {
            vpn.putExtra("auto_save", true);
            vpn.putExtra("auto_connect", source.getBooleanExtra("auto_connect", true));
        }
        startActivity(vpn);
        finish();
    }
}
