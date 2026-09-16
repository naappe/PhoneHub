package mv.phonehub.link

import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import androidx.work.BackoffPolicy
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

class RecoveryWorker(
    appContext: Context,
    params: WorkerParameters
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        if (!PhoneHubService.isEnabled(applicationContext)) {
            return Result.success()
        }

        return try {
            val intent = Intent(applicationContext, PhoneHubService::class.java).apply {
                action = PhoneHubService.ACTION_START
            }
            ContextCompat.startForegroundService(applicationContext, intent)
            Result.success()
        } catch (_: Exception) {
            Result.retry()
        }
    }

    companion object {
        private const val UNIQUE_WORK = "phonehub_recovery"

        fun enqueue(context: Context) {
            val request = OneTimeWorkRequestBuilder<RecoveryWorker>()
                .setInitialDelay(RecoveryPolicy.nextDelaySeconds(0), TimeUnit.SECONDS)
                .setBackoffCriteria(
                    BackoffPolicy.EXPONENTIAL,
                    RecoveryPolicy.nextDelaySeconds(0),
                    TimeUnit.SECONDS
                )
                .build()

            WorkManager.getInstance(context).enqueueUniqueWork(
                UNIQUE_WORK,
                ExistingWorkPolicy.REPLACE,
                request
            )
        }
    }
}
