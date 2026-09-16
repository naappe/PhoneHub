package mv.phonehub.link

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat


data class PairingUiState(
    val serviceEnabled: Boolean,
    val paired: Boolean,
    val permissionRequired: Boolean = false
) {
    val title: String
        get() = when {
            permissionRequired -> "Permission Required"
            !serviceEnabled -> "Service Off"
            paired -> "Active - Paired"
            else -> "Active - Not Paired"
        }
}

class MainActivity : ComponentActivity() {
    private lateinit var pairingStore: PairingStore
    private lateinit var status: TextView
    private lateinit var pairingInfo: TextView
    private lateinit var room: TextView
    private lateinit var enableButton: Button
    private lateinit var pairingButton: Button
    private lateinit var revokeButton: Button
    private lateinit var startButton: Button
    private lateinit var stopButton: Button
    private var pendingRoomCode: String? = null

    private val projectionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        val code = pendingRoomCode
        if (result.resultCode == Activity.RESULT_OK && result.data != null && code != null) {
            val intent = Intent(this, ScreenShareService::class.java).apply {
                action = ScreenShareService.ACTION_START
                putExtra(ScreenShareService.EXTRA_ROOM, code)
                putExtra(ScreenShareService.EXTRA_PROJECTION_DATA, result.data)
            }
            ContextCompat.startForegroundService(this, intent)
            status.text = "Screen sharing active"
            room.text = "Viewer room: $code"
            stopButton.isEnabled = true
            startButton.isEnabled = false
        } else {
            status.text = "Screen sharing permission was not granted"
            pendingRoomCode = null
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        pairingStore = PairingStore(applicationContext)
        requestNotificationPermissionIfNeeded()
        setContentView(buildUi())
        refreshSetupState()
    }

    override fun onResume() {
        super.onResume()
        if (::pairingStore.isInitialized && ::status.isInitialized) refreshSetupState()
    }

    private fun buildUi(): View {
        val pad = (20 * resources.displayMetrics.density).toInt()
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(pad, pad * 2, pad, pad)
            setBackgroundColor(Color.rgb(247, 249, 252))
        }

        val title = TextView(this).apply {
            text = "PhoneHub"
            textSize = 30f
            setTextColor(Color.rgb(15, 23, 42))
            gravity = Gravity.CENTER
        }

        val subtitle = TextView(this).apply {
            text = "Secure background connection to your paired PC"
            textSize = 16f
            setTextColor(Color.rgb(71, 85, 105))
            gravity = Gravity.CENTER
            setPadding(0, pad / 2, 0, pad)
        }

        status = TextView(this).apply {
            text = "Checking service..."
            textSize = 20f
            gravity = Gravity.CENTER
            setTextColor(Color.rgb(30, 64, 175))
            setPadding(0, pad, 0, pad)
        }

        enableButton = Button(this).apply {
            text = "Enable PhoneHub"
            textSize = 17f
            setOnClickListener { enablePhoneHub() }
        }

        pairingInfo = TextView(this).apply {
            text = "No pairing code active"
            textSize = 18f
            gravity = Gravity.CENTER
            setTextColor(Color.rgb(15, 23, 42))
            setPadding(0, pad, 0, pad / 2)
        }

        pairingButton = Button(this).apply {
            text = "Generate Pairing Code"
            textSize = 17f
            setOnClickListener { generatePairingCode() }
        }

        revokeButton = Button(this).apply {
            text = "Revoke Paired PC"
            textSize = 17f
            setOnClickListener { revokePairing() }
        }

        val screenHeading = TextView(this).apply {
            text = "Screen sharing"
            textSize = 18f
            setTextColor(Color.rgb(15, 23, 42))
            setPadding(0, pad * 2, 0, pad / 2)
        }

        room = TextView(this).apply {
            text = "Viewer room will appear here"
            textSize = 18f
            gravity = Gravity.CENTER
            setTextColor(Color.rgb(71, 85, 105))
            setPadding(0, pad / 2, 0, pad)
        }

        startButton = Button(this).apply {
            text = "Start Screen Share"
            textSize = 17f
            setOnClickListener { startShare() }
        }

        stopButton = Button(this).apply {
            text = "Stop Sharing"
            textSize = 17f
            isEnabled = false
            setOnClickListener { stopShare() }
        }

        root.addView(title)
        root.addView(subtitle)
        root.addView(status)
        root.addView(enableButton, fullWidth())
        root.addView(pairingInfo)
        root.addView(pairingButton, fullWidth())
        root.addView(revokeButton, fullWidth())
        root.addView(screenHeading)
        root.addView(room)
        root.addView(startButton, fullWidth())
        root.addView(stopButton, fullWidth())

        return ScrollView(this).apply { addView(root) }
    }

    private fun fullWidth() = LinearLayout.LayoutParams(
        LinearLayout.LayoutParams.MATCH_PARENT,
        LinearLayout.LayoutParams.WRAP_CONTENT
    )

    private fun enablePhoneHub() {
        val intent = Intent(this, PhoneHubService::class.java).apply {
            action = PhoneHubService.ACTION_START
        }
        ContextCompat.startForegroundService(this, intent)
        status.text = "Starting PhoneHub..."
        refreshSetupState()
    }

    private fun generatePairingCode() {
        if (!PhoneHubService.isEnabled(this)) enablePhoneHub()
        val code = pairingStore.createPairingCode()
        pairingInfo.text = "Pairing code: $code\nExpires in 5 minutes"
        pairingButton.text = "Generate New Pairing Code"
    }

    private fun revokePairing() {
        pairingStore.revokePairing()
        pairingInfo.text = "Paired PC revoked"
        refreshSetupState()
    }

    private fun refreshSetupState() {
        val permissionRequired = Build.VERSION.SDK_INT >= 33 &&
            ActivityCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        val state = PairingUiState(
            serviceEnabled = PhoneHubService.isEnabled(this),
            paired = pairingStore.getPairedClient() != null,
            permissionRequired = permissionRequired
        )
        status.text = state.title
        enableButton.isEnabled = !state.serviceEnabled
        enableButton.text = if (state.serviceEnabled) "PhoneHub Enabled" else "Enable PhoneHub"
        pairingButton.isEnabled = !state.paired
        revokeButton.isEnabled = state.paired
        if (state.paired) {
            pairingInfo.text = "Trusted PC paired"
        } else if (!pairingInfo.text.startsWith("Pairing code:")) {
            pairingInfo.text = "No trusted PC paired"
        }
    }

    private fun startShare() {
        pendingRoomCode = createRoomCode()
        status.text = "Approve Android screen sharing..."
        val manager = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        projectionLauncher.launch(manager.createScreenCaptureIntent())
    }

    private fun stopShare() {
        startService(Intent(this, ScreenShareService::class.java).apply {
            action = ScreenShareService.ACTION_STOP
        })
        refreshSetupState()
        room.text = "Viewer room will appear here"
        startButton.isEnabled = true
        stopButton.isEnabled = false
        pendingRoomCode = null
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= 33 &&
            ActivityCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 100)
        }
    }
}
