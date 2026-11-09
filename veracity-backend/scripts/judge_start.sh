#!/bin/sh
# Start command of the full judge build (Dockerfile.judge).
#
# Environment. The image holds a copy of .env.example; anything not already set falls
# back to it, so a judge who never made a .env (or runs plain `docker run`) gets the
# same start-up as one who did. An empty VERA_* value, such as a line "VERA_UPLOAD_SPEED="
# in .env, means "use the default": without this, float("") stops the app at import.
if [ -f .env.defaults ]; then
  already_set=$(export -p)
  set -a
  . ./.env.defaults
  set +a
  eval "$already_set"
fi
for name in $(env | sed -n 's/^\(VERA_[A-Z0-9_]*\)=$/\1/p'); do
  unset "$name"
done

# Spectra-0 and Whisper run at the same time and each takes every core by default,
# so they slow each other down. Spectra-0 barely gains from more threads (1.18 s per
# window on 2, 1.09 s on 10, in Docker on an Apple M5), so it gets about a third of
# the CPUs and Whisper the rest: on that machine the end-of-call wait for Whisper went
# from 24.5 s to 7.6 s. OMP_NUM_THREADS and VERA_WHISPER_THREADS still override it.
cpus=$(nproc)
torch=$((cpus / 3))
[ "$torch" -lt 2 ] && torch=2
whisper=$((cpus - torch))
[ "$whisper" -lt 2 ] && whisper=2
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-$torch}"
export VERA_WHISPER_THREADS="${VERA_WHISPER_THREADS:-$whisper}"
echo "judge build: ${cpus} CPUs, torch ${OMP_NUM_THREADS} threads, whisper ${VERA_WHISPER_THREADS} threads"
if [ -z "$PAYPAL_CLIENT_ID" ] || [ -z "$PAYPAL_CLIENT_SECRET" ]; then
  echo "judge build: no PayPal sandbox keys in .env, so Protected Send uses the in-memory stand-in, not PayPal"
fi
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
