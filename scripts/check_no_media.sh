#!/usr/bin/env bash
# Fails if any tracked file is audio, video, an image, or sits in a data folder (privacy rule).
set -euo pipefail
pattern='\.(mp4|mov|avi|mkv|webm|m4v|wav|mp3|m4a|aac|flac|ogg|opus|jpg|jpeg|png|heic|bmp|tiff|npy|npz)$|^(data|recordings)/'
if matches=$(git ls-files | grep -iE "$pattern"); then
  echo "Media or recordings are tracked by git:" >&2
  echo "$matches" >&2
  exit 1
fi
echo "No media files tracked."
