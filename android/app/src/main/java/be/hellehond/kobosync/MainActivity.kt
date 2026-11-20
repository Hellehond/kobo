package be.hellehond.kobosync

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import be.hellehond.kobosync.reader.ReaderActivity
import be.hellehond.kobosync.ui.AppRoot
import be.hellehond.kobosync.ui.AppViewModel
import be.hellehond.kobosync.ui.KobosyncTheme

class MainActivity : ComponentActivity() {
    private val vm: AppViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        setContent {
            KobosyncTheme {
                AppRoot(vm) { book ->
                    startActivity(Intent(this, ReaderActivity::class.java).putExtra(ReaderActivity.EXTRA_BOOK_ID, book.id))
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        // Pick up what was read on a Kobo, and send what was read here.
        vm.sync(quiet = true)
    }
}
