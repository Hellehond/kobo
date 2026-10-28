"""kobosync - a small self-hosted Kobo sync server for your own (non-store) ebooks.

It speaks the subset of the Kobo store API that Kobo e-readers use for their
library, so books you drop in the library folder are delivered to the devices
through the same channel as store purchases.  Because of that, the devices
treat them as "Kobo" books and sync their reading position back to this
server, which hands it to the other device on its next sync.

Requests that concern real Kobo store content are forwarded to Kobo.
"""

__version__ = "0.1.0"
