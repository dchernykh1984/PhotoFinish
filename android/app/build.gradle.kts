import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.ktlint)
    alias(libs.plugins.detekt)
    alias(libs.plugins.kover)
}

// Release signing comes from the environment, as in ChronometerAndroid, so the
// keystore never lives in the repository: absent (local builds, pull requests),
// the release build stays unsigned; the release run sets it from secrets.
val keystoreFile: String? = System.getenv("KEYSTORE_FILE")

android {
    namespace = "com.dchernykh.photofinish.camera"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.dchernykh.photofinish.camera"
        minSdk = 26
        targetSdk = 36

        // versionCode must grow for an update to install over the last; the
        // release run feeds github.run_number. versionName is PhotoFinish's tag.
        versionCode = System.getenv("VERSION_CODE")?.toIntOrNull() ?: 1
        versionName = System.getenv("VERSION_NAME") ?: "0.1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    signingConfigs {
        if (keystoreFile != null) {
            create("release") {
                storeFile = file(keystoreFile)
                storePassword = System.getenv("KEYSTORE_PASSWORD")
                keyAlias = System.getenv("KEY_ALIAS")
                keyPassword = System.getenv("KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            if (keystoreFile != null) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    lint {
        abortOnError = true
        warningsAsErrors = false
        checkReleaseBuilds = false
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = JvmTarget.JVM_17
    }
}

ktlint {
    android.set(true)
}

detekt {
    buildUponDefaultConfig = true
    config.setFrom(rootProject.file("config/detekt/detekt.yml"))
}

kover {
    reports {
        filters {
            excludes {
                // Generated code, and the Android glue unit tests cannot drive: the
                // camera and the encoder, the activity and its Compose screen. They are
                // tried on the emulator and the phones.
                classes(
                    "*.BuildConfig",
                    "*.R",
                    "*.R$*",
                    "com.dchernykh.photofinish.camera.MainActivity*",
                    "com.dchernykh.photofinish.camera.ui.*",
                    "com.dchernykh.photofinish.camera.capture.CameraStreamer*",
                    "com.dchernykh.photofinish.camera.capture.CameraFormats*",
                    "com.dchernykh.photofinish.camera.Settings*",
                )
            }
        }
        verify {
            rule {
                // The protocol code (stream, sync, pairing, the choice of settings).
                minBound(80)
            }
        }
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.zxing.android.embedded)

    debugImplementation(libs.androidx.compose.ui.tooling)

    testImplementation(libs.junit)
}
