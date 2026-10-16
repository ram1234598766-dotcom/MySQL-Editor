plugins {
    id("com.android.application")
}

val releaseStoreFile = System.getenv("ANDROID_KEYSTORE_FILE")
val releaseStorePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
val releaseKeyAlias = System.getenv("ANDROID_KEY_ALIAS")
val releaseKeyPassword = System.getenv("ANDROID_KEY_PASSWORD")
val releaseSigningConfigured = listOf(
    releaseStoreFile,
    releaseStorePassword,
    releaseKeyAlias,
    releaseKeyPassword
).all { !it.isNullOrBlank() }

val ciBuildNumber = System.getenv("GITHUB_RUN_NUMBER")?.toIntOrNull()?.takeIf { it > 0 }
val explicitVersionCode = System.getenv("MYSQL_EDITOR_VERSION_CODE")?.toIntOrNull()?.takeIf { it > 0 }
val safeVersionCode = explicitVersionCode ?: (100_000 + (ciBuildNumber ?: 1))

android {
    namespace = "com.mysqlidle.mobile"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.mysqlidle.mobile"
        minSdk = 24
        targetSdk = 36
        versionCode = safeVersionCode
        versionName = ciBuildNumber?.let { "3.0.0+$it" } ?: "3.0.0"
    }

    signingConfigs {
        create("release") {
            if (releaseSigningConfigured) {
                storeFile = file(requireNotNull(releaseStoreFile))
                storePassword = requireNotNull(releaseStorePassword)
                keyAlias = requireNotNull(releaseKeyAlias)
                keyPassword = requireNotNull(releaseKeyPassword)
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            if (releaseSigningConfigured) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

}
