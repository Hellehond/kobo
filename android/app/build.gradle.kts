plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

// Version from the release workflow (tag v1.2.3 and the run number); a
// local build is 0.0.0-dev.
val appVersionName = (findProperty("appVersionName") as String?) ?: "0.0.0-dev"
val appVersionCode = ((findProperty("appVersionCode") as String?) ?: "1").toInt()

android {
    namespace = "be.hellehond.kobosync"
    compileSdk {
        version = release(37)
    }

    defaultConfig {
        applicationId = "be.hellehond.kobosync"
        minSdk = 26
        targetSdk = 36
        versionCode = appVersionCode
        versionName = appVersionName
    }

    signingConfigs {
        // The release key comes from the environment (GitHub secrets). Without
        // it, release builds are signed with the debug key so they install.
        create("release") {
            val store = System.getenv("KOBOSYNC_KEYSTORE")
            if (!store.isNullOrBlank()) {
                storeFile = file(store)
                storePassword = System.getenv("KOBOSYNC_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("KOBOSYNC_KEY_ALIAS")
                keyPassword = System.getenv("KOBOSYNC_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = if (System.getenv("KOBOSYNC_KEYSTORE").isNullOrBlank()) {
                signingConfigs.getByName("debug")
            } else {
                signingConfigs.getByName("release")
            }
        }
    }

    compileOptions {
        isCoreLibraryDesugaringEnabled = true
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

kotlin {
    jvmToolchain(21)
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
        optIn.add("org.readium.r2.shared.ExperimentalReadiumApi")
    }
}

dependencies {
    coreLibraryDesugaring(libs.desugar)

    implementation(libs.readium.shared)
    implementation(libs.readium.streamer)
    implementation(libs.readium.navigator)
    implementation(libs.appcompat)
    implementation(libs.fragment)

    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.material3)
    implementation(libs.compose.icons)
    implementation(libs.compose.tooling.preview)
    implementation(libs.activity.compose)
    implementation(libs.lifecycle.viewmodel.compose)
    implementation(libs.lifecycle.runtime.compose)

    implementation(libs.okhttp)
    implementation(libs.coil.compose)
    implementation(libs.coil.okhttp)
    implementation(libs.serialization.json)
    implementation(libs.coroutines.android)

    testImplementation(libs.junit)
    testImplementation(libs.okhttp.mockwebserver)
    testImplementation(libs.coroutines.test)
}
