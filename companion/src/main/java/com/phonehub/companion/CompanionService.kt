package com.phonehub.companion

import android.app.*
import android.content.*
import android.os.*
import android.provider.Settings
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import org.json.JSONObject
import java.net.*
import java.util.concurrent.atomic.AtomicBoolean

class CompanionService : Service() {
    companion object {
        private const val CHANNEL="phonehub_connection"; private const val NOTIFICATION_ID=7001
        private const val PREFS="phonehub"; private const val ENABLED="companion_enabled"
        private const val DISCOVERY_PORT=47321; private const val COMMAND_PORT=47322
        fun enable(c:Context){c.getSharedPreferences(PREFS,0).edit().putBoolean(ENABLED,true).apply();start(c)}
        fun isEnabled(c:Context)=c.getSharedPreferences(PREFS,0).getBoolean(ENABLED,false)
        fun start(c:Context){ContextCompat.startForegroundService(c,Intent(c,CompanionService::class.java))}
    }
    private val running=AtomicBoolean(false)
    private var heartbeatThread:Thread?=null; private var commandThread:Thread?=null
    override fun onCreate(){
        super.onCreate()
        val m=getSystemService(NotificationManager::class.java)
        m.createNotificationChannel(NotificationChannel(CHANNEL,"PhoneHub connection",NotificationManager.IMPORTANCE_LOW))
        startForeground(NOTIFICATION_ID,NotificationCompat.Builder(this,CHANNEL)
            .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth).setContentTitle("PhoneHub")
            .setContentText("Companion service active").setOngoing(true).setSilent(true).build())
        startWorkers()
    }
    private fun startWorkers(){ startHeartbeat(); startCommandServer() }
    private fun deviceId()=Settings.Secure.getString(contentResolver,Settings.Secure.ANDROID_ID)?:"android"
    private fun startHeartbeat(){
        if(!running.compareAndSet(false,true)) return
        heartbeatThread=Thread({
            DatagramSocket().use{socket-> socket.broadcast=true
                while(running.get()){
                    try{
                        val p=JSONObject().put("type","heartbeat").put("version",1).put("device_id",deviceId())
                            .put("device_name",Build.MANUFACTURER+" "+Build.MODEL).put("command_port",COMMAND_PORT)
                            .put("timestamp",System.currentTimeMillis()/1000).toString().toByteArray()
                        socket.send(DatagramPacket(p,p.size,InetAddress.getByName("255.255.255.255"),DISCOVERY_PORT))
                    }catch(_:Exception){}
                    try{Thread.sleep(5000)}catch(_:InterruptedException){break}
                }
            }
        },"phonehub-heartbeat").apply{isDaemon=true;start()}
    }
    private fun startCommandServer(){
        if(commandThread?.isAlive==true)return
        commandThread=Thread({
            try{ServerSocket(COMMAND_PORT).use{server->
                server.soTimeout=2000
                while(running.get()){
                    try{server.accept().use{client->
                        client.soTimeout=5000
                        val line=client.getInputStream().bufferedReader().readLine()?:return@use
                        val req=JSONObject(line); val response=JSONObject().put("version",1)
                        when(req.optString("type")){
                            "ping"->response.put("type","pong").put("device_id",deviceId()).put("device_name",Build.MANUFACTURER+" "+Build.MODEL).put("android_version",Build.VERSION.RELEASE).put("sdk",Build.VERSION.SDK_INT).put("timestamp",System.currentTimeMillis()/1000)
                            else->response.put("type","error").put("message","unsupported command")
                        }
                        client.getOutputStream().bufferedWriter().use{w->w.write(response.toString());w.newLine();w.flush()}
                    }}catch(_:SocketTimeoutException){}catch(_:Exception){}
                }
            }}catch(_:Exception){}
        },"phonehub-command").apply{isDaemon=true;start()}
    }
    override fun onDestroy(){running.set(false);heartbeatThread?.interrupt();commandThread?.interrupt();super.onDestroy()}
    override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int{startWorkers();return START_STICKY}
    override fun onBind(intent:Intent?):IBinder?=null
}
