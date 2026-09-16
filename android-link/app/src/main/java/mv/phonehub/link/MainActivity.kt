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
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

class MainActivity : ComponentActivity() {
    private lateinit var status: TextView
    private lateinit var room: TextView
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
            status.text = "Sharing. Waiting for PC viewer..."
            room.text = "Room code: $code"
            stopButton.isEnabled = true
            startButton.isEnabled = false
        } else {
            status.text = "Screen sharing permission was not granted."
            pendingRoomCode = null
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestNotificationPermissionIfNeeded()
        setContentView(buildUi())
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
            text = "PhoneHub Link"
            textSize = 30f
            setTextColor(Color.rgb(15, 23, 42))
            gravity = Gravity.CENTER
        }

        val subtitle = TextView(this).apply {
            text = "View this phone from a PC on another network"
            textSize = 16f
            setTextColor(Color.rgb(71, 85, 105))
            gravity = Gravity.CENTER
            setPadding(0, pad / 2, 0, pad)
        }

        status = TextView(this).apply {
            text = "Ready"
            textSize = 18f
            gravity = Gravity.CENTER
            setTextColor(Color.rgb(30, 64, 175))
            setPadding(0, pad, 0, pad / 2)
        }

        room = TextView(this).apply {
            text = "Room code will appear here"
            textSize = 24f
            gravity = Gravity.CENTER
            setTextColor(Color.rgb(15, 23, 42))
            setPadding(0, pad / 2, 0, pad)
        }

        startButton = Button(this).apply {
            text = "Start Screen Share"
            textSize = 18f
            setOnClickListener { startShare() }
        }

        stopButton = Button(this).apply {
            text = "Stop Sharing"
            textSize = 18f
            isEnabled = false
            setOnClickListener { stopShare() }
        }

        root.addView(title)
        root.addView(subtitle)
        root.addView(status)
        root.addView(room)
        root.addView(startButton, LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT)
        root.addView(stopButton, LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT)
        return root
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
        status.text = "Stopped"
        room.text = "Room code will appear here"
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
