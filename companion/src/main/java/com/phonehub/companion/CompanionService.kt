package com.phonehub.companion

import android.app.*
import android.content.*
import android.os.*
import android.provider.Settings
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import org.json.JSONObject
import java.net.*
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicBoolean
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

class CompanionService : Service() {
    companion object {
        private const val CHANNEL="phonehub_connection"; private const val NOTIFICATION_ID=7001
        private const val PREFS="phonehub"; private const val ENABLED="companion_enabled"; private const val PAIR_KEY="pair_key"
        private const val DISCOVERY_PORT=47321; private const val COMMAND_PORT=47322
        fun enable(c:Context){
            val p=c.getSharedPreferences(PREFS,0)
            if(!p.contains(PAIR_KEY)){val b=ByteArray(32);java.security.SecureRandom().nextBytes(b);p.edit().putString(PAIR_KEY,android.util.Base64.encodeToString(b,android.util.Base64.NO_WRAP)).apply()}
            p.edit().putBoolean(ENABLED,true).apply();start(c)
        }
        fun isEnabled(c:Context)=c.getSharedPreferences(PREFS,0).getBoolean(ENABLED,false)
        fun start(c:Context){ContextCompat.startForegroundService(c,Intent(c,CompanionService::class.java))}
    }
    private val running=AtomicBoolean(false); private var heartbeatThread:Thread?=null; private var commandThread:Thread?=null
    override fun onCreate(){super.onCreate();val m=getSystemService(NotificationManager::class.java);m.createNotificationChannel(NotificationChannel(CHANNEL,"PhoneHub connection",NotificationManager.IMPORTANCE_LOW));startForeground(NOTIFICATION_ID,NotificationCompat.Builder(this,CHANNEL).setSmallIcon(android.R.drawable.stat_sys_data_bluetooth).setContentTitle("PhoneHub").setContentText("Companion service active").setOngoing(true).setSilent(true).build());startWorkers()}
    private fun startWorkers(){startHeartbeat();startCommandServer()}
    private fun deviceId()=Settings.Secure.getString(contentResolver,Settings.Secure.ANDROID_ID)?:"android"
    private fun keyBytes():ByteArray?{val s=getSharedPreferences(PREFS,0).getString(PAIR_KEY,null)?:return null;return android.util.Base64.decode(s,android.util.Base64.NO_WRAP)}
    private fun hmac(key:ByteArray,data:String):String{val m=Mac.getInstance("HmacSHA256");m.init(SecretKeySpec(key,"HmacSHA256"));return m.doFinal(data.toByteArray()).joinToString(""){"%02x".format(it)}}
    private fun secureEquals(a:String,b:String)=MessageDigest.isEqual(a.toByteArray(),b.toByteArray())
    private fun startHeartbeat(){
        if(!running.compareAndSet(false,true))return
        heartbeatThread=Thread({DatagramSocket().use{socket->socket.broadcast=true;while(running.get()){try{val p=JSONObject().put("type","heartbeat").put("version",1).put("device_id",deviceId()).put("device_name",Build.MANUFACTURER+" "+Build.MODEL).put("command_port",COMMAND_PORT).put("auth","hmac-sha256").put("timestamp",System.currentTimeMillis()/1000).toString().toByteArray();socket.send(DatagramPacket(p,p.size,InetAddress.getByName("255.255.255.255"),DISCOVERY_PORT))}catch(_:Exception){};try{Thread.sleep(5000)}catch(_:InterruptedException){break}}}},"phonehub-heartbeat").apply{isDaemon=true;start()}
    }
    private fun startCommandServer(){
        if(commandThread?.isAlive==true)return
        commandThread=Thread({try{ServerSocket(COMMAND_PORT).use{server->server.soTimeout=2000;while(running.get()){try{server.accept().use{client->client.soTimeout=5000;val line=client.getInputStream().bufferedReader().readLine()?:return@use;val req=JSONObject(line);val response=JSONObject().put("version",1);val key=keyBytes();val ts=req.optLong("timestamp",0);val nonce=req.optString("nonce");val sig=req.optString("signature");val now=System.currentTimeMillis()/1000;val canonical=req.optString("type")+"|"+ts+"|"+nonce;val authorized=key!=null&&nonce.isNotBlank()&&kotlin.math.abs(now-ts)<=30&&secureEquals(hmac(key,canonical),sig)
            if(req.optString("type")=="enroll"){if(key==null)response.put("type","error").put("message","companion not enabled") else response.put("type","enrolled").put("device_id",deviceId()).put("pair_key",android.util.Base64.encodeToString(key,android.util.Base64.NO_WRAP))}
            else if(!authorized)response.put("type","error").put("message","unauthorized")
            else when(req.optString("type")){"ping"->response.put("type","pong").put("device_id",deviceId()).put("device_name",Build.MANUFACTURER+" "+Build.MODEL).put("android_version",Build.VERSION.RELEASE).put("sdk",Build.VERSION.SDK_INT).put("timestamp",now);else->response.put("type","error").put("message","unsupported command")}
            client.getOutputStream().bufferedWriter().use{w->w.write(response.toString());w.newLine();w.flush()}
        }}catch(_:SocketTimeoutException){}catch(_:Exception){}}}}catch(_:Exception){}},"phonehub-command").apply{isDaemon=true;start()}
    }
    override fun onDestroy(){running.set(false);heartbeatThread?.interrupt();commandThread?.interrupt();super.onDestroy()}
    override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int{startWorkers();return START_STICKY}
    override fun onBind(intent:Intent?):IBinder?=null
}
