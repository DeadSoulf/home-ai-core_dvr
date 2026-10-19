#!/bin/sh
# Explicitly prevent the legacy, OpenSSL-1.1-linked helpers from being run with
# the 6.1.11.40 ABI. The API reports the operation as unavailable, not success.
printf '%s\n' 'HCNetSDK 6.1.11.40: this advanced operation needs a separately validated native adapter' >&2
exit 78
