plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}
android {
    namespace = "com.phonehub.companion"
    compileSdk = 35
    signingConfigs {
        create("phonehubRelease") {
            storeFile = rootProject.file("phonehub-release.jks")
            storePassword = System.getenv("PHONEHUB_STORE_PASSWORD")
            keyAlias = System.getenv("PHONEHUB_KEY_ALIAS")
            keyPassword = System.getenv("PHONEHUB_KEY_PASSWORD")
        }
    }
    defaultConfig {
        applicationId = "com.phonehub.companion"
        minSdk = 26
        targetSdk = 35
        versionCode = 84
        versionName = "7.0.0-dev16"
    }
    buildTypes {
        getByName("release") {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("phonehubRelease")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}
dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.activity:activity-ktx:1.10.1")
    implementation("io.github.webrtc-sdk:android:150.7871.01")
}