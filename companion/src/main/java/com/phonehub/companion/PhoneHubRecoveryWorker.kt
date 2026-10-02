package com.phonehub.companion

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

class PhoneHubRecoveryWorker(
    context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        if (!CompanionService.isEnabled(applicationContext)) return Result.success()
        return try {
            CompanionService.start(applicationContext)
            Result.success()
        } catch (_: Exception) {
            Result.retry()
        }
    }
}

object PhoneHubRecovery {
    private const val PERIODIC_WORK = "phonehub-connection-recovery"
    private const val IMMEDIATE_WORK = "phonehub-connection-recovery-now"

    private val connected = Constraints.Builder()
        .setRequiredNetworkType(NetworkType.CONNECTED)
        .build()

    fun schedule(context: Context) {
        if (!CompanionService.isEnabled(context)) return
        val work = PeriodicWorkRequestBuilder<PhoneHubRecoveryWorker>(15, TimeUnit.MINUTES)
            .setConstraints(connected)
            .build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            PERIODIC_WORK,
            ExistingPeriodicWorkPolicy.KEEP,
            work
        )
    }

    fun recoverNow(context: Context) {
        if (!CompanionService.isEnabled(context)) return
        val work = OneTimeWorkRequestBuilder<PhoneHubRecoveryWorker>()
            .setConstraints(connected)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            IMMEDIATE_WORK,
            ExistingWorkPolicy.REPLACE,
            work
        )
    }
}
