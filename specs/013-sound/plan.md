# Implementation Plan: Sound

**Spec**: [spec.md](spec.md)

## Shape

```
android/.../capture/Microphone.kt     AudioRecord into an AAC encoder; each piece stamped on the
                                      frames' clock; run while the main lens is fed
android/.../stream/Aac.kt             the AudioSpecificConfig, and FLV's AAC tags
android/.../stream/FrameStore.kt      an entry marked sound: kept in the newest run, read back,
                                      passed over before a connection's first keyframe
android/.../stream/Uplink.kt          sound sent on the connection, timed from its first frame;
                                      its header once a connection; metadata says it
android/.../stream/RtmpPublisher.kt   RTMP audio messages
android/.../stream/StreamHeader.kt    the sound's config kept with the stream, optional
app/recorder/sources.py               a stream's audio packets too, each with a moment from the
                                      frame before it
app/recorder/segments.py              a segment's audio beside its video; timestamps from a
                                      second before its first frame, so none is negative
app/sound.py                          a camera's sound from a moment: pieces in order, each once;
                                      decoded on one decoder, slowed or sped with the pitch kept
app/widgets/sound.py                  the sound played: Qt's audio output, fed as it plays
app/export.py                         the sound into the MP4, in step with the picture
app/main_window.py                    the Sound switch; the sound started and stopped with Play
```

## Decisions

- **One connection.** The sound goes in the main lens's store and on its connection, in the
  order captured: oldest first, never behind another lens, which waits for the main lens as it
  does now. A connection starts at a keyframe; a piece of sound captured before that frame is
  not sent on it.
- **One clock.** A piece's capture time is read from the microphone's own timestamp on the
  monotonic clock and moved to the clock the frames are stamped on; the RTMP timestamps of
  sound and frames count from the connection's first frame, so the recorder places a piece by
  the frame before it: that frame's moment plus the distance between their timestamps.
- **No negative timestamp.** A segment's timestamps start a second (`LEAD_MS`) after its base: a
  piece of sound captured just before the keyframe that opens a segment arrives after it. A
  Matroska muxer handed a negative one shifts every stream, and the frame times listed would no
  longer name the frames.
- **Once.** The recorder skips a piece at or before the newest it wrote in this run -- sent again
  after a loss --, and the readers drop a piece that overlaps the one before.
- **Played on one decoder.** The pieces of consecutive segments go through one AAC decoder, so
  the sound runs on across a segment's end; FFmpeg's `atempo` changes the speed and keeps the
  pitch, chained for x1/16 to x16.
- **In step.** The sound starts at the moment playing starts from, at its rate; a jump -- a gap,
  a new rate, a seek -- starts it again from there; a sound more than 80 ms off the picture is
  started again.
- **Whose sound.** The camera shown, if its recording has sound; else the camera of the same
  phone whose recording has (`phone` in a lens's settings).

## Tests

Phone: an entry marked sound kept, read back and passed over at a connection's start; the
uplink's timestamps, header and metadata; the publisher's messages; the header's config round
trip, an old header without one. Laptop: a segment's audio beside its video, timestamps from
LEAD_MS; the moments from the video; once though sent again; the reader across segments, the
rates' sample counts, a gap's silence; the export's track; the window's switch, the sound
started and stopped. On the emulator: the phone's sound into a recorder.
